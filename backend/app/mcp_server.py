"""MCP server exposing the logistics tools. Run: python -m app.mcp_server (stdio).

Every tool returns an envelope {ok, data | error, error_type, details} so the caller
never has to guess whether a call worked."""
from typing import Any, Callable, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from app import tools, read_tools

mcp = FastMCP("logistics-tools")


def _safe(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Dict[str, Any]:
    try:
        return {"ok": True, "data": fn(*args, **kwargs)}
    except tools.ToolExecutionError as exc:
        return {"ok": False, "error": str(exc), "error_type": type(exc).__name__, "details": exc.details}
    except Exception as exc:  # unexpected: surface it, never swallow
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "error_type": "UnexpectedError", "details": {}}


@mcp.tool()
def parse_order(raw_prompt: str, override_items: Optional[List[Dict[str, Any]]] = None,
                override_city: Optional[str] = None, override_address: Optional[str] = None,
                override_priority: Optional[str] = None) -> Dict[str, Any]:
    """Parse and validate a shipment request against the product catalog."""
    return _safe(tools.parse_order_tool, raw_prompt, override_items, override_city, override_address, override_priority)


@mcp.tool()
def check_inventory(items: List[Dict[str, Any]], destination_city: str) -> Dict[str, Any]:
    """Check stock in all warehouses and choose the best fulfilling warehouse."""
    return _safe(tools.check_inventory_tool, items, destination_city)


@mcp.tool()
def estimate_route(warehouse_id: str, destination_city: str) -> Dict[str, Any]:
    """Distance and ETA from warehouse to destination (Google Maps or simulated)."""
    return _safe(read_tools.estimate_route_tool, warehouse_id, destination_city)


@mcp.tool()
def reserve_inventory(order_id: str, warehouse_id: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Atomically and idempotently reserve stock for an order."""
    return _safe(tools.reserve_inventory_atomic_tool, order_id, warehouse_id, items)


@mcp.tool()
def release_reservation(order_id: str) -> Dict[str, Any]:
    """Release reserved stock for an order (compensating action)."""
    return _safe(tools.release_inventory_reservation_tool, order_id)


@mcp.tool()
def pick_items(order_id: str, warehouse_id: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Produce the pick manifest for reserved items."""
    return _safe(tools.pick_items_tool, order_id, warehouse_id, items)


@mcp.tool()
def package_order(order_id: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Choose certified packaging for weight, fragility and hazmat."""
    return _safe(tools.package_order_tool, order_id, items)


@mcp.tool()
def list_eligible_carriers(is_fragile: bool, is_hazmat: bool,
                           excluded_carrier_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """List carriers certified for the cargo, excluding failed ones."""
    return _safe(read_tools.list_eligible_carriers_tool, is_fragile, is_hazmat, excluded_carrier_ids)


@mcp.tool()
def book_carrier(order_id: str, priority: str, is_fragile: bool, is_hazmat: bool, total_weight_kg: float,
                 simulate_failure: bool = False, excluded_carrier_ids: Optional[List[str]] = None,
                 preferred_carrier_id: Optional[str] = None) -> Dict[str, Any]:
    """Book a simulated carrier and persist the tracking id. May fail with CarrierBookingError."""
    return _safe(tools.book_carrier_tool, order_id, priority, is_fragile, is_hazmat, total_weight_kg,
                 simulate_failure, excluded_carrier_ids, preferred_carrier_id)


@mcp.tool()
def verify_persisted_records(order_id: str) -> Dict[str, Any]:
    """Verify the order against persisted SQLite records only."""
    return _safe(tools.verify_persisted_records_tool, order_id)


@mcp.tool()
def get_inventory(product_id: Optional[str] = None) -> Dict[str, Any]:
    """Current stock per warehouse."""
    return _safe(read_tools.get_inventory_tool, product_id)


@mcp.tool()
def get_shipment_status(order_id: Optional[str] = None) -> Dict[str, Any]:
    """Status of a shipment by order or tracking id (latest if omitted)."""
    return _safe(read_tools.get_shipment_status_tool, order_id)


@mcp.tool()
def list_shipments(limit: int = 10) -> Dict[str, Any]:
    """Recent shipments."""
    return _safe(read_tools.list_shipments_tool, limit)


@mcp.tool()
def set_carrier_outage(carrier_id: str, offline: bool) -> Dict[str, Any]:
    """Toggle a simulated carrier outage."""
    return _safe(read_tools.set_carrier_outage_tool, carrier_id, offline)


if __name__ == "__main__":
    mcp.run(transport="stdio")
