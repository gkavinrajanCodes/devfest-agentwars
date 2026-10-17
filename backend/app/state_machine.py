"""Explicit workflow state machine. Only the orchestrator calls transition()."""
from datetime import datetime, timezone

TRANSITIONS = {
    "SUBMITTED": {"VALIDATED", "FAILED"},
    "VALIDATED": {"INVENTORY_CHECKED", "FAILED"},
    "INVENTORY_CHECKED": {"INVENTORY_RESERVED", "FAILED"},
    "INVENTORY_RESERVED": {"ITEMS_PICKED", "FAILED"},
    "ITEMS_PICKED": {"PACKAGED", "FAILED"},
    "PACKAGED": {"CARRIER_BOOKED", "RETRYING", "FAILED"},
    "RETRYING": {"CARRIER_BOOKED", "RETRYING", "FAILED"},
    "CARRIER_BOOKED": {"VERIFIED", "FAILED"},
    "VERIFIED": {"COMPLETED", "FAILED"},
    "COMPLETED": set(),
    "FAILED": set(),
}
TERMINAL = {"COMPLETED", "FAILED"}


class InvalidTransition(Exception):
    pass


def can_transition(current: str, new: str) -> bool:
    return new in TRANSITIONS.get(current, set())


def transition(conn, order_id: str, new_status: str, failure_reason: str | None = None) -> str:
    """Validate and persist a status change atomically. Returns the previous status."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            raise InvalidTransition(f"Order {order_id} does not exist")
        current = row["status"]
        if not can_transition(current, new_status):
            raise InvalidTransition(f"Illegal transition {current} -> {new_status} for {order_id}")
        conn.execute(
            "UPDATE orders SET status = ?, failure_reason = COALESCE(?, failure_reason), updated_at = ? WHERE id = ?",
            (new_status, failure_reason, datetime.now(timezone.utc).isoformat(), order_id),
        )
        conn.execute("COMMIT")
        return current
    except Exception:
        conn.execute("ROLLBACK")
        raise
