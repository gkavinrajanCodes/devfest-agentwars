"""FastAPI application entrypoint for Logistics Autopilot."""
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.database import init_db, seed_db, reset_demo_database, get_connection
from app.models import (
    ShipmentCreateRequest,
    OrderDetailResponse,
    WarehouseStockInfo,
    CarrierInfo
)
from app.orchestrator import orchestrator
from app import agent as llm_agent
from app.mcp_client import client as mcp_client


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Ensure database tables and initial seed data exist; warm the MCP session."""
    init_db()
    seed_db()
    mcp_client.start()
    yield


app = FastAPI(
    title="Logistics Autopilot API",
    description="Autonomous logistics workflow orchestrator with atomic state transitions and recovery",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for local Vite development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str


@app.get("/api/agent/info")
def agent_info():
    """What the agent layer is actually running with right now (no guessing in the UI)."""
    return {**llm_agent.agent_info(), "mcp_connected": bool(mcp_client.tool_names),
            "mcp_tools": mcp_client.tool_names, "mcp_error": mcp_client.start_error}


@app.post("/api/chat")
def chat(req: ChatRequest):
    """Conversational control: request, inspect and manage logistics in natural language."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message is empty")
    return llm_agent.chat(req.message)

@app.get("/api/health")
def api_health():
    return {"name": "Logistics Autopilot API", "status": "ONLINE", "version": "1.0.0"}


@app.get("/")
def read_root():
    dist_index = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist" / "index.html"
    if dist_index.exists():
        return FileResponse(dist_index)
    return {"name": "Logistics Autopilot API", "status": "ONLINE", "version": "1.0.0"}

@app.post("/api/shipments", response_model=OrderDetailResponse)
def create_shipment(req: ShipmentCreateRequest):
    """Execute end-to-end shipment request from natural language or structured items."""
    try:
        result = orchestrator.execute_shipment_workflow(req)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/shipments/{order_id}", response_model=OrderDetailResponse)
def get_shipment(order_id: str):
    """Fetch order details, real-time workflow timeline, and verification certificate."""
    order = orchestrator.get_order_detail(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Shipment order not found")
    return order

@app.get("/api/shipments")
def list_shipments(limit: int = 20):
    """List recent shipments with status and tracking."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT o.id, o.raw_prompt, o.customer_name, o.destination_city, o.priority,
                   o.status, o.tracking_id, o.created_at, o.total_cost,
                   w.name as warehouse_name, c.name as carrier_name
            FROM orders o
            LEFT JOIN warehouses w ON o.warehouse_id = w.id
            LEFT JOIN carriers c ON o.carrier_id = c.id
            ORDER BY o.created_at DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

@app.get("/api/inventory")
def get_inventory():
    """Get real-time stock levels, reservations, and bin locations across all warehouses."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT i.warehouse_id, w.name as warehouse_name, w.city, w.state,
                   i.product_id, p.name as product_name, p.sku,
                   i.total_stock, i.reserved_stock,
                   (i.total_stock - i.reserved_stock) as available_stock,
                   i.bin_location
            FROM inventory i
            JOIN warehouses w ON i.warehouse_id = w.id
            JOIN products p ON i.product_id = p.id
            ORDER BY i.warehouse_id ASC, p.id ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

@app.get("/api/warehouses")
def get_warehouses():
    """List all logistics hub warehouses."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM warehouses WHERE is_active = 1").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

@app.get("/api/carriers", response_model=List[CarrierInfo])
def get_carriers():
    """List all simulated delivery carriers with reliability ratings and outage flags."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM carriers ORDER BY reliability_rating DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

@app.post("/api/carriers/{carrier_id}/toggle-failure")
def toggle_carrier_failure(carrier_id: str):
    """Toggle simulated API failure for a carrier to demonstrate resilience."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT simulate_failure FROM carriers WHERE id = ?", (carrier_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Carrier not found")
        new_state = 0 if row["simulate_failure"] else 1
        conn.execute("UPDATE carriers SET simulate_failure = ? WHERE id = ?", (new_state, carrier_id))
        return {"carrier_id": carrier_id, "simulate_failure": bool(new_state)}
    finally:
        conn.close()

@app.post("/api/demo/reset")
def reset_demo():
    """Deterministic demo reset for judges: restores inventory and clears orders."""
    reset_demo_database()
    return {"status": "SUCCESS", "message": "Demo database successfully reset to clean initial state."}

@app.get("/api/demo/scenarios")
def get_demo_scenarios():
    """Predefined one-click demo scenarios for the presentation."""
    return [
        {
            "id": "scenario-standard-happy",
            "title": "Standard Express Dispatch",
            "badge": "Happy Path",
            "badge_color": "emerald",
            "prompt": "Dispatch 2 Industrial LiDAR Scanners and 1 Thermal Imaging Core to Chicago hub via express freight.",
            "description": "Validates stock at Alpha Hub (East Coast), reserves inventory atomically, selects fragile-certified packaging, books the best eligible carrier, and verifies the result against persisted records.",
            "simulate_carrier_failure": False,
            "priority": "EXPRESS"
        },
        {
            "id": "scenario-carrier-recovery",
            "title": "Carrier Outage & Autonomous Fallback",
            "badge": "Self-Healing Recovery",
            "badge_color": "amber",
            "prompt": "Emergency shipment of 1 Solid-State Battery Pack 48V and 2 Servo Actuators to Seattle facility overnight.",
            "description": "Forces a 503 on the first-choice carrier. The orchestrator observes the failure, the diagnosis agent picks an eligible hazmat-certified alternative, and the booking is retried without losing order state.",
            "simulate_carrier_failure": True,
            "priority": "URGENT"
        },
        {
            "id": "scenario-multi-item-hazmat",
            "title": "Heavy Hazmat Drone Power Cell",
            "badge": "Certified Packaging",
            "badge_color": "purple",
            "prompt": "Ship 3 Aerospace Lithium Battery Modules to Dallas defense contractor.",
            "description": "Evaluates heavy hazmat compliance, selects DOT-certified reinforced hazmat drum, picks from specialized bin H-02-01, and dispatches via hazmat-certified carrier.",
            "simulate_carrier_failure": False,
            "priority": "STANDARD"
        },
        {
            "id": "scenario-duplicate-idempotency",
            "title": "Duplicate Request / Idempotency Test",
            "badge": "Double-Spend Prevention",
            "badge_color": "blue",
            "prompt": "Ship 2 Industrial LiDAR Scanners to Boston research lab.",
            "description": "Submits with a fixed idempotency key. Sending it again returns the same shipment without reserving stock twice.",
            "simulate_carrier_failure": False,
            "idempotency_key": "IDEMP-DEMO-LOCKED-001",
            "priority": "EXPRESS"
        }
    ]


# Unified single-port deployment: serve frontend build if dist/ exists
DIST_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if (DIST_DIR / "index.html").exists():
    if (DIST_DIR / "assets").exists():
        app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="static_assets")

    @app.get("/{full_path:path}")
    def serve_frontend_spa(full_path: str):
        target = DIST_DIR / full_path
        if target.exists() and target.is_file():
            return FileResponse(target)
        return FileResponse(DIST_DIR / "index.html")

