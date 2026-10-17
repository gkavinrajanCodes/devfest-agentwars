"""LLM layer built on Google ADK. Three roles, two models:

- ParserAgent    (fast model): natural language -> structured order, validated against the catalog
- DiagnosisAgent (pro model):  failure + eligible carriers -> recovery proposal
- ChatAgent      (fast model): conversational control, calling logistics tools over MCP

The LLM never writes DB rows and never decides success. Every function here returns None or a
deterministic result when no key is set or any LLM call fails; callers record which path ran."""
import asyncio
import json
import os
import re
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
if os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]

FAST_MODEL = os.environ.get("GEMINI_FAST_MODEL", "gemini-flash-latest")
PRO_MODEL = os.environ.get("GEMINI_PRO_MODEL", "gemini-3.5-flash")
LLM_TIMEOUT_S = float(os.environ.get("LLM_TIMEOUT_S", "30"))
APP = "logistics_autopilot"


def llm_enabled() -> bool:
    return bool(os.environ.get("GOOGLE_API_KEY")) and os.environ.get("LLM_DISABLED") != "1"


def agent_info() -> Dict[str, Any]:
    return {"llm_enabled": llm_enabled(), "fast_model": FAST_MODEL, "pro_model": PRO_MODEL,
            "maps_enabled": bool(os.environ.get("GOOGLE_MAPS_API_KEY")), "sdk": "google-adk"}


async def _ask(agent: Any, text: str):
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    svc = InMemorySessionService()
    runner = Runner(agent=agent, app_name=APP, session_service=svc)
    await svc.create_session(app_name=APP, user_id="user", session_id="s1")
    msg = types.Content(role="user", parts=[types.Part(text=text)])
    final, calls = "", []
    async for ev in runner.run_async(user_id="user", session_id="s1", new_message=msg):
        for fc in ev.get_function_calls() or []:
            calls.append(fc.name)
        if ev.is_final_response() and ev.content and ev.content.parts:
            final = "".join(p.text or "" for p in ev.content.parts)
    return final, calls


def _ask_sync(agent: Any, text: str):
    return asyncio.run(asyncio.wait_for(_ask(agent, text), LLM_TIMEOUT_S))


def _json_from(text: str) -> Optional[dict]:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------- parser (fast model)
def parse_request(prompt: str, catalog: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Returns {items, city, priority, source:'llm', model} or None (caller falls back to regex)."""
    if not llm_enabled():
        return None
    try:
        from google.adk.agents import Agent
        cat = "\n".join(f"- {c['id']}: {c['name']} ({c['sku']})" for c in catalog)
        agent = Agent(
            name="parser_agent", model=FAST_MODEL,
            instruction=("Extract a shipment order from the user's text. Reply with ONLY JSON: "
                         '{"items":[{"product_id":"PROD-001","quantity":2}],"destination_city":"Chicago",'
                         '"priority":"STANDARD|EXPRESS|URGENT"}. Use only product ids from this catalog:\n' + cat),
        )
        text, _ = _ask_sync(agent, prompt)
        data = _json_from(text)
        valid = {c["id"] for c in catalog}
        if not data or not data.get("items"):
            return None
        items = []
        for it in data["items"]:
            qty = int(it.get("quantity", 0))
            if it.get("product_id") not in valid or qty <= 0:
                return None  # reject hallucinated products; deterministic parser takes over
            items.append({"product_id": it["product_id"], "quantity": qty})
        prio = str(data.get("priority", "EXPRESS")).upper()
        return {"items": items, "city": data.get("destination_city"),
                "priority": prio if prio in ("STANDARD", "EXPRESS", "URGENT") else "EXPRESS",
                "source": "llm", "model": FAST_MODEL}
    except Exception:
        return None


# ---------------------------------------------------------------- diagnosis (pro model)
def diagnose_failure(error: str, details: Dict[str, Any], eligible: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pick a recovery carrier. LLM proposals are accepted only if the carrier id is in `eligible`."""
    usable = [c for c in eligible if not c.get("reported_offline")] or eligible
    fallback = {"source": "deterministic", "model": None,
                "carrier_id": usable[0]["id"] if usable else None,
                "reason": "Highest-rated eligible carrier that is not reported offline."}
    if not usable or not llm_enabled():
        return fallback
    try:
        from google.adk.agents import Agent
        agent = Agent(
            name="diagnosis_agent", model=PRO_MODEL,
            instruction=("A carrier booking failed. Diagnose the cause and choose the best alternative from the "
                         'eligible list. Reply with ONLY JSON: {"carrier_id":"<id from list>","reason":"<one sentence>"}.'),
        )
        text, _ = _ask_sync(agent, json.dumps({"error": error, "details": details, "eligible": usable}))
        data = _json_from(text)
        if data and data.get("carrier_id") in {c["id"] for c in usable}:
            return {"source": "llm", "model": PRO_MODEL, "carrier_id": data["carrier_id"],
                    "reason": str(data.get("reason", ""))[:300]}
    except Exception:
        pass
    return fallback


# ---------------------------------------------------------------- chat (fast model + MCP tools)
def _mcp(name: str, **args: Any) -> Dict[str, Any]:
    from app.mcp_client import client, ToolFailure
    try:
        return client.call(name, **args)["data"]
    except ToolFailure as exc:
        return {"error": str(exc)}


def list_inventory(product_id: str) -> dict:
    """List stock per warehouse. Pass a product id like PROD-001 to filter, or an empty string for all products."""
    return _mcp("get_inventory", product_id=product_id or None)


def shipment_status(order_id: str) -> dict:
    """Get status of a shipment by order id or tracking id. Pass an empty string for the latest shipment."""
    return _mcp("get_shipment_status", order_id=order_id or None)


def recent_shipments() -> dict:
    """List recent shipments."""
    return _mcp("list_shipments", limit=10)


def set_carrier_outage(carrier_id: str, offline: bool) -> dict:
    """Mark a carrier (CARRIER-APEX, CARRIER-SWIFT, CARRIER-TITAN) offline or online."""
    return _mcp("set_carrier_outage", carrier_id=carrier_id, offline=offline)


def create_shipment(request_text: str) -> dict:
    """Create and execute a shipment from natural language, e.g. 'ship 2 lidar scanners to Chicago'."""
    from app.orchestrator import orchestrator
    from app.models import ShipmentCreateRequest
    o = orchestrator.execute_shipment_workflow(ShipmentCreateRequest(raw_prompt=request_text))
    return {"order_id": o["id"], "status": o["status"], "tracking_id": o["tracking_id"],
            "carrier": o["carrier_name"], "warehouse": o["warehouse_name"], "failure_reason": o["failure_reason"]}


CARRIER_WORDS = {"apex": "CARRIER-APEX", "swift": "CARRIER-SWIFT", "titan": "CARRIER-TITAN"}


def _chat_deterministic(message: str) -> Dict[str, Any]:
    m = message.lower()
    actions: List[str] = []
    carrier = next((cid for w, cid in CARRIER_WORDS.items() if w in m), None)
    if carrier and re.search(r"\b(outage|offline|down|fail)", m):
        r = set_carrier_outage(carrier, True)
        actions.append("set_carrier_outage")
        return {"reply": f"{carrier} is now marked offline. Shipments will fail over to an eligible alternative." if "error" not in r else r["error"], "actions": actions}
    if carrier and re.search(r"\b(online|restore|back up|fix)", m):
        r = set_carrier_outage(carrier, False)
        actions.append("set_carrier_outage")
        return {"reply": f"{carrier} is back online." if "error" not in r else r["error"], "actions": actions}
    if re.search(r"\b(ship|send|dispatch|deliver)\b", m):
        r = create_shipment(message)
        actions.append("create_shipment")
        if r["status"] == "COMPLETED":
            return {"reply": f"Shipment {r['order_id']} completed via {r['carrier']} from {r['warehouse']}. Tracking ID: {r['tracking_id']}.", "actions": actions, "order_id": r["order_id"]}
        return {"reply": f"Shipment {r['order_id']} ended as {r['status']}: {r['failure_reason']}", "actions": actions, "order_id": r["order_id"]}
    if re.search(r"\b(stock|inventory|available|left)\b", m):
        inv = list_inventory("")["inventory"]
        actions.append("list_inventory")
        lines = [f"{i['warehouse_id']} {i['product_name']}: {i['available_stock']} available" for i in inv]
        return {"reply": "Current stock:\n" + "\n".join(lines), "actions": actions}
    if re.search(r"\b(status|track|where|last|latest|shipment|order)\b", m):
        tid = re.search(r"(TRK-[A-Z]+-[0-9A-F]+|ORD-\d+-[0-9A-F]+)", message.upper())
        s = shipment_status(tid.group(1) if tid else "")
        actions.append("shipment_status")
        if "error" in s:
            return {"reply": s["error"], "actions": actions}
        return {"reply": f"Order {s['order_id']} is {s['status']} (destination {s['destination_city']}, tracking {s['tracking_id'] or 'n/a'}).", "actions": actions, "order_id": s["order_id"]}
    return {"reply": "I can ship items (\"ship 2 lidar scanners to Chicago\"), check stock, track a shipment, or mark a carrier offline/online.", "actions": actions}


def chat(message: str) -> Dict[str, Any]:
    if llm_enabled():
        try:
            from google.adk.agents import Agent
            agent = Agent(
                name="chat_agent", model=FAST_MODEL,
                instruction=("You are the Logistics Autopilot operator assistant. Use tools for every fact about "
                             "stock, shipments and carriers. Never invent order ids, tracking ids or stock numbers. "
                             "If a tool returns an error, say so plainly. Keep answers short."),
                tools=[list_inventory, shipment_status, recent_shipments, set_carrier_outage, create_shipment],
            )
            text, calls = _ask_sync(agent, message)
            if text:
                return {"reply": text, "actions": calls, "source": "llm", "model": FAST_MODEL}
        except Exception as exc:
            out = _chat_deterministic(message)
            out.update(source="deterministic", llm_error=f"{type(exc).__name__}: {exc}"[:200])
            return out
    out = _chat_deterministic(message)
    out["source"] = "deterministic"
    return out
