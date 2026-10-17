"""Automated test suite for Logistics Autopilot."""
import pytest
import os


from app.database import init_db, seed_db, reset_demo_database, get_connection
from app.orchestrator import WorkflowOrchestrator
from app.models import ShipmentCreateRequest, OrderStatus

@pytest.fixture(autouse=True)
def setup_test_db():
    init_db()
    seed_db()
    reset_demo_database()
    yield
    reset_demo_database()

def test_happy_path_workflow_execution():
    """Verify that a standard shipment request executes end-to-end, persists, and verifies."""
    orchestrator = WorkflowOrchestrator()
    req = ShipmentCreateRequest(
        raw_prompt="Ship 2 Industrial LiDAR Scanners and 1 Thermal Imaging Core to Chicago hub via express freight.",
        destination_city="Chicago",
        priority="EXPRESS",
        simulate_carrier_failure=False
    )
    
    order = orchestrator.execute_shipment_workflow(req)
    
    assert order is not None
    assert order["status"] == OrderStatus.COMPLETED.value
    assert order["warehouse_id"] == "WH-EAST"
    assert order["carrier_id"] is not None
    assert order["tracking_id"] is not None
    assert order["tracking_id"].startswith("TRK-")
    assert order["packaging_id"] == "PKG-FRG-S"  # Fragile items certified box
    assert len(order["items"]) == 2
    
    # Check verification block
    assert order["verification"] is not None
    assert order["verification"]["is_valid"] is True
    assert order["verification"]["carrier_tracking_verified"] is True
    assert order["verification"]["reservations_intact"] is True

    # Check database persistence
    conn = get_connection()
    db_order = conn.execute("SELECT * FROM orders WHERE id = ?", (order["id"],)).fetchone()
    assert db_order is not None
    assert db_order["status"] == OrderStatus.COMPLETED.value
    assert db_order["tracking_id"] == order["tracking_id"]

    # Check inventory delta (50 - 2 = 48 available for PROD-001)
    inv = conn.execute(
        "SELECT total_stock, reserved_stock FROM inventory WHERE warehouse_id = 'WH-EAST' AND product_id = 'PROD-001'"
    ).fetchone()
    assert inv["reserved_stock"] == 2
    conn.close()

def test_carrier_outage_autonomous_recovery():
    """Verify that when primary carrier fails, orchestrator detects outage and recovers via backup carrier."""
    orchestrator = WorkflowOrchestrator()
    req = ShipmentCreateRequest(
        raw_prompt="Emergency shipment of 1 Solid-State Battery Pack 48V to Seattle facility.",
        destination_city="Seattle",
        priority="URGENT",
        simulate_carrier_failure=True
    )
    
    order = orchestrator.execute_shipment_workflow(req)
    
    assert order is not None
    assert order["status"] == OrderStatus.COMPLETED.value
    
    # Check that carrier recovery occurred
    step_names = [s["step_name"] for s in order["timeline"]]
    assert "CARRIER_OUTAGE_DETECTED" in step_names
    assert "CARRIER_RECOVERED" in step_names

    # Outage detected and autonomous fallback succeeded with valid tracking ID
    assert order["carrier_id"] in ["CARRIER-SWIFT", "CARRIER-TITAN"]
    assert order["tracking_id"].startswith("TRK-")
    assert order["verification"]["is_valid"] is True

def test_idempotent_duplicate_prevention():
    """Verify that submitting the same request with the same idempotency key returns the existing order."""
    orchestrator = WorkflowOrchestrator()
    key = "IDEMP-TEST-UNIQUE-999"
    
    req1 = ShipmentCreateRequest(
        raw_prompt="Ship 2 Industrial LiDAR Scanners to Boston research lab.",
        idempotency_key=key
    )
    order1 = orchestrator.execute_shipment_workflow(req1)
    assert order1["status"] == OrderStatus.COMPLETED.value

    # Query warehouse reserved stock
    conn = get_connection()
    inv_after_1 = conn.execute(
        "SELECT reserved_stock FROM inventory WHERE warehouse_id = 'WH-EAST' AND product_id = 'PROD-001'"
    ).fetchone()["reserved_stock"]
    conn.close()

    # Re-submit with same key
    req2 = ShipmentCreateRequest(
        raw_prompt="Ship 2 Industrial LiDAR Scanners to Boston research lab.",
        idempotency_key=key
    )
    order2 = orchestrator.execute_shipment_workflow(req2)
    
    assert order1["id"] == order2["id"]
    assert order1["tracking_id"] == order2["tracking_id"]

    # Verify inventory was NOT double-reserved
    conn = get_connection()
    inv_after_2 = conn.execute(
        "SELECT reserved_stock FROM inventory WHERE warehouse_id = 'WH-EAST' AND product_id = 'PROD-001'"
    ).fetchone()["reserved_stock"]
    conn.close()

    assert inv_after_1 == inv_after_2

def test_deterministic_demo_reset():
    """Verify that reset_demo_database restores inventory levels and clears past orders."""
    orchestrator = WorkflowOrchestrator()
    req = ShipmentCreateRequest(
        raw_prompt="Ship 5 Industrial LiDAR Scanners to New York.",
        destination_city="New York"
    )
    order = orchestrator.execute_shipment_workflow(req)
    assert order["status"] == OrderStatus.COMPLETED.value

    # Reset
    reset_demo_database()

    conn = get_connection()
    orders_count = conn.execute("SELECT COUNT(*) as c FROM orders").fetchone()["c"]
    assert orders_count == 0

    inv = conn.execute(
        "SELECT total_stock, reserved_stock FROM inventory WHERE warehouse_id = 'WH-EAST' AND product_id = 'PROD-001'"
    ).fetchone()
    assert inv["total_stock"] == 50
    assert inv["reserved_stock"] == 0
    conn.close()

def test_out_of_stock_inventory_handling():
    """Verify that requests exceeding warehouse inventory fail cleanly without partial reservations."""
    orchestrator = WorkflowOrchestrator()
    req = ShipmentCreateRequest(
        raw_prompt="Ship 999 Industrial LiDAR Scanners to Chicago hub.",
        destination_city="Chicago"
    )
    order = orchestrator.execute_shipment_workflow(req)
    assert order["status"] == OrderStatus.FAILED.value
    assert "Insufficient inventory" in order["failure_reason"]

    # Verify no stock was reserved
    conn = get_connection()
    inv_east = conn.execute(
        "SELECT reserved_stock FROM inventory WHERE warehouse_id = 'WH-EAST' AND product_id = 'PROD-001'"
    ).fetchone()["reserved_stock"]
    inv_west = conn.execute(
        "SELECT reserved_stock FROM inventory WHERE warehouse_id = 'WH-WEST' AND product_id = 'PROD-001'"
    ).fetchone()["reserved_stock"]
    assert inv_east == 0
    assert inv_west == 0
    conn.close()
