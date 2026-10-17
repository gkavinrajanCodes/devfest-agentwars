"""Read/inspect/manage tools and routing, exposed over MCP alongside the workflow tools."""
from typing import Any, Dict, List, Optional

from app.database import get_connection
from app.maps import estimate_route
from app.tools import ToolExecutionError


def estimate_route_tool(warehouse_id: str, destination_city: str) -> Dict[str, Any]:
    """Distance and ETA from a warehouse to a city (Google Maps, or simulated with disclosure)."""
    return estimate_route(warehouse_id, destination_city)


def list_eligible_carriers_tool(is_fragile: bool, is_hazmat: bool,
                                excluded_carrier_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Carriers that are active, online and certified for the cargo. Ground truth for recovery."""
    excluded = set(excluded_carrier_ids or [])
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM carriers WHERE is_active = 1 ORDER BY reliability_rating DESC").fetchall()
        out = []
        for c in rows:
            if c["id"] in excluded or (is_fragile and not c["supports_fragile"]) or (is_hazmat and not c["supports_hazmat"]):
                continue
            out.append({"id": c["id"], "name": c["name"], "reliability_rating": c["reliability_rating"],
                        "service_level": c["service_level"], "reported_offline": bool(c["simulate_failure"])})
        return {"eligible": out}
    finally:
        conn.close()


def get_inventory_tool(product_id: Optional[str] = None) -> Dict[str, Any]:
    """Stock levels per warehouse and product."""
    conn = get_connection()
    try:
        sql = ("SELECT i.warehouse_id, i.product_id, p.name AS product_name, i.total_stock, i.reserved_stock, "
               "(i.total_stock - i.reserved_stock) AS available_stock, i.bin_location "
               "FROM inventory i JOIN products p ON p.id = i.product_id")
        args: tuple = ()
        if product_id:
            sql += " WHERE i.product_id = ?"
            args = (product_id,)
        return {"inventory": [dict(r) for r in conn.execute(sql + " ORDER BY i.warehouse_id, i.product_id", args)]}
    finally:
        conn.close()


def get_shipment_status_tool(order_id: Optional[str] = None) -> Dict[str, Any]:
    """Status of one shipment, or the most recent one when order_id is omitted."""
    conn = get_connection()
    try:
        if order_id:
            row = conn.execute("SELECT * FROM orders WHERE id = ? OR tracking_id = ?", (order_id, order_id)).fetchone()
        else:
            row = conn.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT 1").fetchone()
        if not row:
            raise ToolExecutionError("No matching shipment found")
        return {"order_id": row["id"], "status": row["status"], "destination_city": row["destination_city"],
                "tracking_id": row["tracking_id"], "carrier_id": row["carrier_id"],
                "warehouse_id": row["warehouse_id"], "failure_reason": row["failure_reason"]}
    finally:
        conn.close()


def list_shipments_tool(limit: int = 10) -> Dict[str, Any]:
    """Recent shipments, newest first."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, status, destination_city, tracking_id, carrier_id FROM orders ORDER BY created_at DESC LIMIT ?",
            (limit,)).fetchall()
        return {"shipments": [dict(r) for r in rows]}
    finally:
        conn.close()


def set_carrier_outage_tool(carrier_id: str, offline: bool) -> Dict[str, Any]:
    """Mark a simulated carrier offline/online (chaos switch for the demo)."""
    conn = get_connection()
    try:
        cur = conn.execute("UPDATE carriers SET simulate_failure = ? WHERE id = ?", (1 if offline else 0, carrier_id))
        if cur.rowcount == 0:
            raise ToolExecutionError(f"Unknown carrier {carrier_id}")
        return {"carrier_id": carrier_id, "offline": offline}
    finally:
        conn.close()
