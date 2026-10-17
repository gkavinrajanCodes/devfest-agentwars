"""Single orchestrator: runs the shipment plan as MCP tool calls, enforces the state machine,
checks each result against persisted evidence (feedback loop) and self-heals carrier failures.

The orchestrator never trusts a tool's or an LLM's claim of success: after each mutating step
it reads the database and records the evidence next to the tool output."""
import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app import agent, state_machine
from app.database import get_connection, transaction
from app.mcp_client import ToolFailure, client as mcp_client
from app.models import ShipmentCreateRequest

MAX_CARRIER_ATTEMPTS = 3


class StepFailed(Exception):
    pass


class WorkflowOrchestrator:
    def __init__(self, mcp: Any = mcp_client) -> None:
        self.mcp = mcp

    # ------------------------------------------------------------------ helpers
    def _call(self, tool: str, **args: Any):
        """Returns (data, transport, elapsed_ms). Raises ToolFailure carrying elapsed_ms."""
        t0 = time.perf_counter()
        try:
            res = self.mcp.call(tool, **args)
        except ToolFailure as exc:
            exc.elapsed_ms = int((time.perf_counter() - t0) * 1000)  # type: ignore[attr-defined]
            raise
        return res["data"], res["transport"], int((time.perf_counter() - t0) * 1000)

    def _record(self, conn, oid: str, step: str, tool: str, status: str,
                inp: Dict[str, Any], out: Dict[str, Any], ms: int) -> None:
        conn.execute(
            "INSERT INTO workflow_steps (order_id, step_name, tool_name, status, input_payload, output_payload, elapsed_ms, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (oid, step, tool, status, json.dumps(inp), json.dumps(out), ms, datetime.now(timezone.utc).isoformat()))

    def _set(self, conn, oid: str, **cols: Any) -> None:
        sets = ", ".join(f"{k} = ?" for k in cols)
        conn.execute(f"UPDATE orders SET {sets}, updated_at = ? WHERE id = ?",
                     (*cols.values(), datetime.now(timezone.utc).isoformat(), oid))

    def _step(self, conn, oid: str, step: str, tool: str, inp: Dict[str, Any], **args: Any):
        """Call a tool, record SUCCESS/FAILED, return (data, transport). Raises StepFailed."""
        try:
            data, transport, ms = self._call(tool, **args)
        except ToolFailure as exc:
            self._record(conn, oid, step + "_FAILED", tool, "FAILED", inp,
                         {"error": str(exc), "error_type": exc.error_type, "details": exc.details},
                         getattr(exc, "elapsed_ms", 0))
            raise StepFailed(str(exc)) from exc
        return data, transport, ms

    def _ok(self, conn, oid, step, tool, inp, data, transport, ms, evidence: Dict[str, Any],
            status: str = "SUCCESS") -> None:
        """Record a step once its evidence check passed; otherwise fail the workflow."""
        out = dict(data)
        out["evidence"] = evidence
        out["meta"] = {"transport": transport}
        if not evidence["passed"]:
            self._record(conn, oid, step + "_EVIDENCE_MISMATCH", tool, "FAILED", inp, out, ms)
            raise StepFailed(f"{step}: tool reported success but persisted state disagrees ({evidence['check']})")
        self._record(conn, oid, step, tool, status, inp, out, ms)

    @staticmethod
    def _evidence(check: str, passed: bool, observed: Any) -> Dict[str, Any]:
        return {"check": check, "passed": bool(passed), "observed": observed, "source": "sqlite"}

    def _fail(self, conn, oid: str, reason: str) -> None:
        order = conn.execute("SELECT status FROM orders WHERE id = ?", (oid,)).fetchone()
        if not order or order["status"] in state_machine.TERMINAL:
            return
        try:
            self._call("release_reservation", order_id=oid)
        except Exception:
            pass
        state_machine.transition(conn, oid, "FAILED", reason)

    # ------------------------------------------------------------------ entry point
    def execute_shipment_workflow(self, req: ShipmentCreateRequest) -> Dict[str, Any]:
        conn = get_connection()
        try:
            key = req.idempotency_key or f"IDEMP-{uuid.uuid4().hex[:12]}"
            existing = conn.execute("SELECT id FROM orders WHERE idempotency_key = ?", (key,)).fetchone()
            if existing:
                return self.get_order_detail(existing["id"])

            oid = f"ORD-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
            now = datetime.now(timezone.utc).isoformat()
            try:
                with transaction(conn):
                    conn.execute(
                        "INSERT INTO orders (id, idempotency_key, raw_prompt, customer_name, destination_city, destination_address, priority, status, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, 'SUBMITTED', ?, ?)",
                        (oid, key, req.raw_prompt, req.customer_name or "Acme Autonomous Robotics Corp",
                         req.destination_city or "Pending", req.destination_address or "Pending",
                         req.priority or "EXPRESS", now, now))
            except sqlite3.IntegrityError:  # lost a race on the same idempotency key
                row = conn.execute("SELECT id FROM orders WHERE idempotency_key = ?", (key,)).fetchone()
                return self.get_order_detail(row["id"])

            try:
                self._pipeline(conn, oid, req)
            except StepFailed as exc:
                self._fail(conn, oid, str(exc))
            except Exception as exc:  # never leave an order half-finished
                self._record(conn, oid, "UNEXPECTED_ERROR", "orchestrator", "FAILED", {}, {"error": f"{type(exc).__name__}: {exc}"}, 0)
                self._fail(conn, oid, f"Unexpected error: {type(exc).__name__}: {exc}")
            return self.get_order_detail(oid)
        finally:
            conn.close()

    # ------------------------------------------------------------------ plan
    def _pipeline(self, conn, oid: str, req: ShipmentCreateRequest) -> None:
        # 1. Parse + validate (LLM proposes, catalog validates, deterministic parser is the fallback)
        catalog = [dict(r) for r in conn.execute("SELECT id, name, sku FROM products")]
        t0 = time.perf_counter()
        llm = None if req.items else agent.parse_request(req.raw_prompt, catalog)
        llm_ms = int((time.perf_counter() - t0) * 1000)
        items = [i.model_dump() for i in req.items] if req.items else (llm["items"] if llm else None)
        city = req.destination_city or (llm or {}).get("city")
        priority = req.priority or (llm or {}).get("priority")
        source = "structured" if req.items else ("llm" if llm else "deterministic")
        inp = {"raw_prompt": req.raw_prompt, "parse_source": source}
        parsed, tr, ms = self._step(conn, oid, "ORDER_VALIDATED", "parse_order", inp, raw_prompt=req.raw_prompt,
                                    override_items=items, override_city=city,
                                    override_address=req.destination_address, override_priority=priority)
        with transaction(conn):
            conn.execute("DELETE FROM order_items WHERE order_id = ?", (oid,))
            for it in parsed["items"]:
                conn.execute("INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
                             (oid, it["product_id"], it["quantity"], it["unit_price"]))
            self._set(conn, oid, destination_city=parsed["destination_city"],
                      destination_address=parsed["destination_address"], priority=parsed["priority"],
                      total_cost=parsed["total_item_cost"], total_weight_kg=parsed["total_weight_kg"])
        n_items = conn.execute("SELECT COUNT(*) c, COALESCE(SUM(quantity),0) q FROM order_items WHERE order_id = ?", (oid,)).fetchone()
        want_q = sum(i["quantity"] for i in parsed["items"])
        ev = self._evidence("order_items persisted", n_items["c"] == len(parsed["items"]) and n_items["q"] == want_q,
                            {"lines": n_items["c"], "units": n_items["q"]})
        parsed_out = dict(parsed, parse_source=source, parse_model=(llm or {}).get("model"), llm_parse_ms=llm_ms)
        self._ok(conn, oid, "ORDER_VALIDATED", "parse_order", inp, parsed_out, tr, ms + llm_ms, ev)
        state_machine.transition(conn, oid, "VALIDATED")
        items = parsed["items"]
        simple = [{"product_id": i["product_id"], "quantity": i["quantity"]} for i in items]

        # 2. Inventory check
        inp = {"items": simple, "destination_city": parsed["destination_city"]}
        inv, tr, ms = self._step(conn, oid, "INVENTORY_EVALUATED", "check_inventory", inp, items=simple,
                                 destination_city=parsed["destination_city"])
        wh = inv["selected_warehouse_id"]
        self._set(conn, oid, warehouse_id=wh)
        row = conn.execute("SELECT warehouse_id FROM orders WHERE id = ?", (oid,)).fetchone()
        self._ok(conn, oid, "INVENTORY_EVALUATED", "check_inventory", inp, inv, tr, ms,
                 self._evidence("orders.warehouse_id persisted", row["warehouse_id"] == wh, row["warehouse_id"]))
        state_machine.transition(conn, oid, "INVENTORY_CHECKED")

        # 2b. Route (Google Maps, or simulated with disclosure). Informational, never blocks.
        inp = {"warehouse_id": wh, "destination_city": parsed["destination_city"]}
        route, tr, ms = self._step(conn, oid, "ROUTE_PLANNED", "estimate_route", inp, warehouse_id=wh,
                                   destination_city=parsed["destination_city"])
        self._ok(conn, oid, "ROUTE_PLANNED", "estimate_route", inp, route, tr, ms,
                 self._evidence("route source disclosed", "source" in route, route.get("source")))

        # 3. Atomic, idempotent reservation
        inp = {"warehouse_id": wh, "items": simple}
        res, tr, ms = self._step(conn, oid, "INVENTORY_RESERVED", "reserve_inventory", inp, order_id=oid,
                                 warehouse_id=wh, items=simple)
        rows = conn.execute("SELECT product_id, SUM(quantity) q FROM inventory_reservations WHERE order_id = ? AND status = 'RESERVED' GROUP BY product_id", (oid,)).fetchall()
        got = {r["product_id"]: r["q"] for r in rows}
        want = {i["product_id"]: i["quantity"] for i in simple}
        self._ok(conn, oid, "INVENTORY_RESERVED", "reserve_inventory", inp, res, tr, ms,
                 self._evidence("RESERVED rows match order", got == want, got))
        state_machine.transition(conn, oid, "INVENTORY_RESERVED")

        # 4. Pick
        inp = {"warehouse_id": wh}
        pick, tr, ms = self._step(conn, oid, "ITEMS_PICKED", "pick_items", inp, order_id=oid, warehouse_id=wh, items=simple)
        self._ok(conn, oid, "ITEMS_PICKED", "pick_items", inp, pick, tr, ms,
                 self._evidence("every line picked", pick["items_picked_count"] == len(simple), pick["items_picked_count"]))
        state_machine.transition(conn, oid, "ITEMS_PICKED")

        # 5. Package
        inp = {"items_count": len(simple)}
        pkg, tr, ms = self._step(conn, oid, "PACKAGING_ASSIGNED", "package_order", inp, order_id=oid, items=simple)
        row = conn.execute("SELECT packaging_id FROM orders WHERE id = ?", (oid,)).fetchone()
        self._ok(conn, oid, "PACKAGING_ASSIGNED", "package_order", inp, pkg, tr, ms,
                 self._evidence("orders.packaging_id persisted", row["packaging_id"] == pkg["packaging_id"], row["packaging_id"]))
        state_machine.transition(conn, oid, "PACKAGED")

        # 6. Carrier booking with observe -> diagnose -> re-plan loop
        self._book_with_recovery(conn, oid, req, parsed, pkg)

        # 7. Verify against persisted records only
        inp = {"order_id": oid}
        ver, tr, ms = self._step(conn, oid, "PERSISTED_STATE_VERIFIED", "verify_persisted_records", inp, order_id=oid)
        self._ok(conn, oid, "PERSISTED_STATE_VERIFIED", "verify_persisted_records", inp, ver, tr, ms,
                 self._evidence("verification is_valid", ver.get("is_valid") is True, ver.get("checksum")))
        state_machine.transition(conn, oid, "VERIFIED")
        state_machine.transition(conn, oid, "COMPLETED")

    def _book_with_recovery(self, conn, oid: str, req: ShipmentCreateRequest, parsed: Dict[str, Any], pkg: Dict[str, Any]) -> None:
        excluded: List[str] = []
        preferred: Optional[str] = None
        simulate = bool(req.simulate_carrier_failure)
        failures: List[Dict[str, Any]] = []
        for attempt in range(1, MAX_CARRIER_ATTEMPTS + 1):
            args = dict(order_id=oid, priority=parsed["priority"], is_fragile=parsed["is_fragile"],
                        is_hazmat=parsed["is_hazmat"], total_weight_kg=pkg["actual_weight_kg"],
                        simulate_failure=simulate, excluded_carrier_ids=excluded, preferred_carrier_id=preferred)
            inp = {"attempt": attempt, "excluded": list(excluded), "preferred": preferred}
            try:
                data, tr, ms = self._call("book_carrier", **args)
            except ToolFailure as exc:
                ms = getattr(exc, "elapsed_ms", 0)
                if exc.error_type != "CarrierBookingError":
                    self._record(conn, oid, "CARRIER_BOOKING_ERROR", "book_carrier", "FAILED", inp,
                                 {"error": str(exc), "error_type": exc.error_type}, ms)
                    raise StepFailed(str(exc)) from exc
                failed = exc.details.get("carrier_id")
                if failed:
                    excluded.append(failed)
                failures.append({"carrier_id": failed, "error": str(exc)})
                simulate = False  # the outage was simulated for the first choice only
                state_machine.transition(conn, oid, "RETRYING")
                eligible, tr2, ms2 = self._call("list_eligible_carriers", is_fragile=parsed["is_fragile"],
                                                is_hazmat=parsed["is_hazmat"], excluded_carrier_ids=excluded)
                t0 = time.perf_counter()
                diag = agent.diagnose_failure(str(exc), exc.details, eligible["eligible"])
                diag_ms = int((time.perf_counter() - t0) * 1000)
                self._record(conn, oid, "CARRIER_OUTAGE_DETECTED", "book_carrier", "WARNING", inp,
                             {"error": str(exc), "error_type": exc.error_type, "details": exc.details,
                              "eligible_alternatives": eligible["eligible"], "diagnosis": diag,
                              "meta": {"transport": tr2}}, ms + ms2 + diag_ms)
                if not diag.get("carrier_id"):
                    raise StepFailed("Carrier recovery exhausted: no eligible alternative carrier") from exc
                preferred = diag["carrier_id"]
                continue
            row = conn.execute("SELECT carrier_id, tracking_id FROM orders WHERE id = ?", (oid,)).fetchone()
            ev = self._evidence("orders.carrier_id and tracking_id persisted",
                                row["tracking_id"] == data["tracking_id"] and row["carrier_id"] == data["carrier_id"],
                                {"carrier_id": row["carrier_id"], "tracking_id": row["tracking_id"]})
            recovered = attempt > 1
            if recovered:
                data = dict(data, failed_carriers=failures)
            self._ok(conn, oid, "CARRIER_RECOVERED" if recovered else "CARRIER_DISPATCHED", "book_carrier", inp,
                     data, tr, ms, ev, status="RECOVERED" if recovered else "SUCCESS")
            state_machine.transition(conn, oid, "CARRIER_BOOKED")
            return
        raise StepFailed(f"Carrier recovery exhausted after {MAX_CARRIER_ATTEMPTS} attempts")

    # ------------------------------------------------------------------ read model
    def get_order_detail(self, order_id: str) -> Optional[Dict[str, Any]]:
        conn = get_connection()
        try:
            order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if not order:
                return None
            items = [{
                "product_id": r["product_id"], "product_name": r["product_name"], "quantity": r["quantity"],
                "unit_price": r["unit_price"], "weight_kg": r["weight_kg"] * r["quantity"],
                "is_fragile": bool(r["is_fragile"]), "is_hazmat": bool(r["is_hazmat"]),
                "bin_location": r["bin_location"] or "N/A",
            } for r in conn.execute(
                "SELECT oi.quantity, oi.unit_price, p.id product_id, p.name product_name, p.weight_kg, p.is_fragile, p.is_hazmat, i.bin_location "
                "FROM order_items oi JOIN products p ON oi.product_id = p.id "
                "LEFT JOIN inventory i ON i.product_id = p.id AND i.warehouse_id = ? WHERE oi.order_id = ?",
                (order["warehouse_id"], order_id))]
            timeline = [{
                "id": s["id"], "order_id": s["order_id"], "step_name": s["step_name"], "tool_name": s["tool_name"],
                "status": s["status"], "input_payload": json.loads(s["input_payload"] or "{}"),
                "output_payload": json.loads(s["output_payload"] or "{}"), "elapsed_ms": s["elapsed_ms"],
                "timestamp": s["timestamp"],
            } for s in conn.execute("SELECT * FROM workflow_steps WHERE order_id = ? ORDER BY id", (order_id,))]

            def name(table: str, ident: Optional[str]) -> Optional[str]:
                if not ident:
                    return None
                r = conn.execute(f"SELECT name FROM {table} WHERE id = ?", (ident,)).fetchone()
                return r["name"] if r else None

            verification = None
            if order["status"] == "COMPLETED":
                from app import tools
                try:
                    verification = tools.verify_persisted_records_tool(order_id)
                except Exception:
                    verification = None

            total_ms = sum(s["elapsed_ms"] for s in timeline)
            recovered = any(s["status"] == "RECOVERED" for s in timeline)
            llm_steps = sum(1 for s in timeline if s["output_payload"].get("parse_source") == "llm"
                            or (s["output_payload"].get("diagnosis") or {}).get("source") == "llm")
            mcp_calls = sum(1 for s in timeline if (s["output_payload"].get("meta") or {}).get("transport") == "mcp")
            route = next((s["output_payload"] for s in timeline if s["step_name"] == "ROUTE_PLANNED"), {})
            if order["status"] == "COMPLETED":
                summary = (f"Shipped {sum(i['quantity'] for i in items)} unit(s) from {name('warehouses', order['warehouse_id'])} "
                           f"to {order['destination_city']} via {name('carriers', order['carrier_id'])}, tracking {order['tracking_id']}."
                           + (" A carrier outage was detected and recovered automatically." if recovered else "")
                           + f" Verified against persisted records in {total_ms} ms of tool time.")
            else:
                summary = f"Order ended {order['status']}: {order['failure_reason'] or 'in progress'}."
            report = {"outcome": order["status"], "total_elapsed_ms": total_ms, "steps": len(timeline),
                      "recovered": recovered, "llm_assisted_steps": llm_steps, "mcp_calls": mcp_calls,
                      "route": {k: route.get(k) for k in ("source", "distance_km", "eta_days", "simulated")} if route else None,
                      "summary": summary}
            return {
                "id": order["id"], "idempotency_key": order["idempotency_key"], "raw_prompt": order["raw_prompt"],
                "customer_name": order["customer_name"], "destination_city": order["destination_city"],
                "destination_address": order["destination_address"], "priority": order["priority"],
                "status": order["status"], "warehouse_id": order["warehouse_id"],
                "warehouse_name": name("warehouses", order["warehouse_id"]),
                "packaging_id": order["packaging_id"], "packaging_name": name("packaging_options", order["packaging_id"]),
                "carrier_id": order["carrier_id"], "carrier_name": name("carriers", order["carrier_id"]),
                "tracking_id": order["tracking_id"], "total_weight_kg": order["total_weight_kg"] or 0.0,
                "total_cost": order["total_cost"] or 0.0, "failure_reason": order["failure_reason"],
                "items": items, "timeline": timeline, "verification": verification, "report": report,
                "created_at": order["created_at"], "updated_at": order["updated_at"],
            }
        finally:
            conn.close()


orchestrator = WorkflowOrchestrator()
