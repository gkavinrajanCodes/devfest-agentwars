"""State machine, concurrency, idempotency races, MCP, LLM guardrails, chat and HTTP API."""
import threading

import pytest
from fastapi.testclient import TestClient

from app import agent, state_machine, tools
from app.database import get_connection, init_db, reset_demo_database, seed_db
from app.mcp_client import ToolFailure, client as mcp
from app.models import ShipmentCreateRequest
from app.orchestrator import WorkflowOrchestrator


@pytest.fixture(autouse=True)
def fresh_db():
    init_db()
    seed_db()
    reset_demo_database()
    yield
    reset_demo_database()


def _new_order(conn, oid="ORD-T-1", status="SUBMITTED"):
    conn.execute(
        "INSERT INTO orders (id, idempotency_key, raw_prompt, customer_name, destination_city, destination_address, priority, status, created_at, updated_at) "
        "VALUES (?, ?, 'x', 'c', 'Chicago', 'a', 'EXPRESS', ?, 't', 't')", (oid, oid, status))


# ---- state machine -------------------------------------------------------
def test_illegal_transition_rejected_and_state_unchanged():
    conn = get_connection()
    _new_order(conn)
    with pytest.raises(state_machine.InvalidTransition):
        state_machine.transition(conn, "ORD-T-1", "COMPLETED")
    assert conn.execute("SELECT status FROM orders WHERE id='ORD-T-1'").fetchone()["status"] == "SUBMITTED"
    state_machine.transition(conn, "ORD-T-1", "VALIDATED")
    with pytest.raises(state_machine.InvalidTransition):
        state_machine.transition(conn, "ORD-T-1", "SUBMITTED")  # no going back
    conn.close()


def test_terminal_states_are_final():
    conn = get_connection()
    _new_order(conn, "ORD-T-2", "COMPLETED")
    with pytest.raises(state_machine.InvalidTransition):
        state_machine.transition(conn, "ORD-T-2", "FAILED")
    conn.close()


def test_completed_order_walked_the_legal_path():
    o = WorkflowOrchestrator().execute_shipment_workflow(
        ShipmentCreateRequest(raw_prompt="Ship 1 Precision Servo Actuator to Boston"))
    assert o["status"] == "COMPLETED"
    names = [s["step_name"] for s in o["timeline"]]
    assert names == ["ORDER_VALIDATED", "INVENTORY_EVALUATED", "ROUTE_PLANNED", "INVENTORY_RESERVED",
                     "ITEMS_PICKED", "PACKAGING_ASSIGNED", "CARRIER_DISPATCHED", "PERSISTED_STATE_VERIFIED"]
    assert all(s["output_payload"]["evidence"]["passed"] for s in o["timeline"])


# ---- concurrency / idempotency ------------------------------------------
def test_concurrent_reservations_never_oversell():
    # 40 units exist in WH-WEST for PROD-001. 20 threads each try to reserve 3 (60 > 40).
    conn = get_connection()
    for i in range(20):
        _new_order(conn, f"ORD-C-{i:02d}")
    conn.close()
    results = []

    def work(i):
        try:
            tools.reserve_inventory_atomic_tool(f"ORD-C-{i:02d}", "WH-WEST", [{"product_id": "PROD-001", "quantity": 3}])
            results.append("ok")
        except tools.InventoryShortageError:
            results.append("short")

    ts = [threading.Thread(target=work, args=(i,)) for i in range(20)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    conn = get_connection()
    inv = conn.execute("SELECT total_stock, reserved_stock FROM inventory WHERE warehouse_id='WH-WEST' AND product_id='PROD-001'").fetchone()
    conn.close()
    assert inv["reserved_stock"] <= inv["total_stock"] == 40
    assert inv["reserved_stock"] == 3 * results.count("ok")
    assert results.count("ok") == 13 and results.count("short") == 7


def test_reserve_is_idempotent_per_order():
    conn = get_connection()
    _new_order(conn, "ORD-I-1")
    conn.close()
    args = ("ORD-I-1", "WH-EAST", [{"product_id": "PROD-002", "quantity": 4}])
    tools.reserve_inventory_atomic_tool(*args)
    again = tools.reserve_inventory_atomic_tool(*args)
    assert again["idempotent_replay"] is True
    conn = get_connection()
    assert conn.execute("SELECT reserved_stock FROM inventory WHERE warehouse_id='WH-EAST' AND product_id='PROD-002'").fetchone()[0] == 4
    conn.close()


def test_same_idempotency_key_in_parallel_creates_one_order():
    outs = []

    def work():
        outs.append(WorkflowOrchestrator().execute_shipment_workflow(
            ShipmentCreateRequest(raw_prompt="Ship 2 Industrial LiDAR Scanners to Boston", idempotency_key="RACE-1")))

    ts = [threading.Thread(target=work) for _ in range(5)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len({o["id"] for o in outs}) == 1
    conn = get_connection()
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
    assert conn.execute("SELECT SUM(reserved_stock) FROM inventory WHERE product_id='PROD-001'").fetchone()[0] == 2
    conn.close()


# ---- recovery ------------------------------------------------------------
def test_recovery_uses_a_different_eligible_carrier_and_is_certified():
    o = WorkflowOrchestrator().execute_shipment_workflow(ShipmentCreateRequest(
        raw_prompt="Ship 1 Solid-State Battery Pack to Seattle", simulate_carrier_failure=True))
    assert o["status"] == "COMPLETED" and o["report"]["recovered"] is True
    warn = next(s for s in o["timeline"] if s["step_name"] == "CARRIER_OUTAGE_DETECTED")
    failed = warn["output_payload"]["details"]["carrier_id"]
    assert o["carrier_id"] != failed
    assert o["carrier_id"] in ("CARRIER-SWIFT", "CARRIER-TITAN")  # hazmat-certified only
    assert warn["output_payload"]["diagnosis"]["source"] == "deterministic"


def test_all_carriers_down_fails_cleanly_and_releases_stock():
    conn = get_connection()
    conn.execute("UPDATE carriers SET simulate_failure = 1")
    conn.close()
    o = WorkflowOrchestrator().execute_shipment_workflow(
        ShipmentCreateRequest(raw_prompt="Ship 2 Industrial LiDAR Scanners to Chicago"))
    assert o["status"] == "FAILED" and "exhausted" in o["failure_reason"].lower()
    conn = get_connection()
    assert conn.execute("SELECT SUM(reserved_stock) FROM inventory").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM inventory_reservations WHERE status='RESERVED'").fetchone()[0] == 0
    assert conn.execute("SELECT tracking_id FROM orders").fetchone()[0] is None  # nothing fabricated
    conn.close()


def test_diagnosis_rejects_llm_proposal_for_ineligible_carrier(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake")
    monkeypatch.setenv("LLM_DISABLED", "0")
    monkeypatch.setattr(agent, "_ask_sync", lambda a, t: ('{"carrier_id": "CARRIER-INVENTED", "reason": "x"}', []))
    eligible = [{"id": "CARRIER-SWIFT", "reported_offline": False}]
    d = agent.diagnose_failure("boom", {}, eligible)
    assert d["carrier_id"] == "CARRIER-SWIFT" and d["source"] == "deterministic"


def test_diagnosis_accepts_valid_llm_proposal(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake")
    monkeypatch.setenv("LLM_DISABLED", "0")
    monkeypatch.setattr(agent, "_ask_sync", lambda a, t: ('{"carrier_id": "CARRIER-TITAN", "reason": "ground ok"}', []))
    eligible = [{"id": "CARRIER-SWIFT", "reported_offline": False}, {"id": "CARRIER-TITAN", "reported_offline": False}]
    d = agent.diagnose_failure("boom", {}, eligible)
    assert d["carrier_id"] == "CARRIER-TITAN" and d["source"] == "llm"


def test_parser_rejects_hallucinated_product(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake")
    monkeypatch.setenv("LLM_DISABLED", "0")
    monkeypatch.setattr(agent, "_ask_sync", lambda a, t: ('{"items":[{"product_id":"PROD-999","quantity":1}]}', []))
    assert agent.parse_request("ship stuff", [{"id": "PROD-001", "name": "n", "sku": "s"}]) is None


# ---- MCP -----------------------------------------------------------------
def test_mcp_server_lists_and_executes_tools_over_stdio():
    d = mcp.call("get_inventory")
    assert d["transport"] == "mcp"
    assert {"parse_order", "reserve_inventory", "book_carrier", "verify_persisted_records"} <= set(mcp.tool_names)
    assert len(d["data"]["inventory"]) == 8
    with pytest.raises(ToolFailure):
        mcp.call("get_shipment_status", order_id="NOPE")


# ---- chat + HTTP API ------------------------------------------------------
def test_chat_offline_ships_and_reports_real_data():
    r = agent.chat("please ship 1 thermal imaging core to Denver")
    assert r["source"] == "deterministic" and "create_shipment" in r["actions"]
    assert "TRK-" in r["reply"]
    s = agent.chat("where is my last shipment?")
    assert r["order_id"] in s["reply"]


def test_http_api_end_to_end():
    from app.main import app
    with TestClient(app) as c:
        info = c.get("/api/agent/info").json()
        assert info["mcp_connected"] is True and info["llm_enabled"] is False
        r = c.post("/api/shipments", json={"raw_prompt": "Ship 2 servo actuators to Austin"})
        assert r.status_code == 200 and r.json()["status"] == "COMPLETED"
        assert r.json()["report"]["mcp_calls"] >= 7
        assert c.get(f"/api/shipments/{r.json()['id']}").json()["tracking_id"] == r.json()["tracking_id"]
        assert c.post("/api/chat", json={"message": "stock please"}).json()["actions"] == ["list_inventory"]
        assert c.post("/api/demo/reset").json()["status"] == "SUCCESS"
        assert c.get("/api/shipments").json() == []
