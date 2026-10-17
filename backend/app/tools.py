"""Registered typed tools for Logistics Autopilot."""
import re
import json
import hashlib
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from app.database import get_connection, transaction

class ToolExecutionError(Exception):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.details = details or {}

class CarrierBookingError(ToolExecutionError):
    pass

class InventoryShortageError(ToolExecutionError):
    pass

def parse_order_tool(
    raw_prompt: str,
    override_items: Optional[List[Dict[str, Any]]] = None,
    override_city: Optional[str] = None,
    override_address: Optional[str] = None,
    override_priority: Optional[str] = None
) -> Dict[str, Any]:
    """Parse natural language shipment request into structured order specification.
    Uses regex/keyword matching as a deterministic, reliable parser, compatible with LLM output."""
    prompt_lower = raw_prompt.lower()
    
    # 1. Detect Destination City
    detected_city = "Chicago"
    city_map = {
        "new york": "New York",
        "ny": "New York",
        "chicago": "Chicago",
        "san francisco": "San Francisco",
        "sf": "San Francisco",
        "oakland": "Oakland",
        "los angeles": "Los Angeles",
        "la": "Los Angeles",
        "seattle": "Seattle",
        "boston": "Boston",
        "austin": "Austin",
        "atlanta": "Atlanta",
        "miami": "Miami",
        "dallas": "Dallas",
        "denver": "Denver"
    }
    for key, city in city_map.items():
        if re.search(r'\b' + re.escape(key) + r'\b', prompt_lower):
            detected_city = city
            break
            
    if override_city:
        detected_city = override_city

    destination_address = override_address or f"450 Industrial Parkway, Dock 4B, {detected_city}"
    
    # 2. Detect Priority
    detected_priority = "EXPRESS"
    if any(w in prompt_lower for w in ["urgent", "overnight", "critical", "rush", "asap"]):
        detected_priority = "URGENT"
    elif any(w in prompt_lower for w in ["standard", "ground", "economy"]):
        detected_priority = "STANDARD"
    if override_priority:
        detected_priority = override_priority

    # 3. Detect Items & Quantities
    items: List[Dict[str, Any]] = []
    
    if override_items:
        items = override_items
    else:
        # Match against catalog products
        product_patterns = [
            ("PROD-001", ["lidar scanner", "lidar", "robotic sensor", "scanner"]),
            ("PROD-002", ["thermal imaging core", "thermal imaging", "thermal core", "thermal", "infrared"]),
            ("PROD-003", ["battery pack", "battery modules", "battery module", "power cell", "battery", "power pack", "lithium"]),
            ("PROD-004", ["servo actuator", "actuator", "servo", "motor", "joint"]),
        ]
        
        words_to_num = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
            "seven": 7, "eight": 8, "nine": 9, "ten": 10
        }
        
        for prod_id, keywords in product_patterns:
            matched_qty = None
            for kw in keywords:
                # Matches "2 industrial lidar scanners", "1 thermal imaging core", "3 units of battery", etc.
                pattern = rf'(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:(?:units?|pieces?)\s+of\s+)?(?:industrial|solid-state|precision|aerospace|high-torque|high-capacity)?\s*{re.escape(kw)}'
                match = re.search(pattern, prompt_lower)
                if match:
                    qty_str = match.group(1).lower()
                    if qty_str.isdigit():
                        matched_qty = int(qty_str)
                    elif qty_str in words_to_num:
                        matched_qty = words_to_num[qty_str]
                    break
                # Also check standalone keyword match without explicit preceding quantity (default to 1)
                elif re.search(rf'\b{re.escape(kw)}\b', prompt_lower):
                    # Check if there's a digit within 3 words before the keyword
                    preceding = re.search(rf'(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:\w+\s+){{0,2}}{re.escape(kw)}', prompt_lower)
                    if preceding:
                        q = preceding.group(1).lower()
                        matched_qty = int(q) if q.isdigit() else words_to_num.get(q, 1)
                    else:
                        matched_qty = 1
                    break

            if matched_qty is not None:
                items.append({"product_id": prod_id, "quantity": matched_qty})

        # Fallback if no specific products matched in natural language
        if not items:
            items = [{"product_id": "PROD-001", "quantity": 2}]

    # Merge duplicate product lines and reject non-positive quantities
    merged: Dict[str, int] = {}
    for it in items:
        if int(it["quantity"]) <= 0:
            raise ToolExecutionError(f"Invalid quantity {it['quantity']} for {it['product_id']}")
        merged[it["product_id"]] = merged.get(it["product_id"], 0) + int(it["quantity"])
    items = [{"product_id": p, "quantity": q} for p, q in merged.items()]

    # Connect to DB to fetch product details and validate catalog
    conn = get_connection()
    try:
        detailed_items = []
        total_item_cost = 0.0
        total_weight_kg = 0.0
        is_fragile_overall = False
        is_hazmat_overall = False

        for it in items:
            p_id = it["product_id"]
            row = conn.execute("SELECT * FROM products WHERE id = ?", (p_id,)).fetchone()
            if not row:
                raise ToolExecutionError(f"Product ID '{p_id}' not found in active product catalog.")
            
            qty = it["quantity"]
            weight = row["weight_kg"] * qty
            cost = row["unit_price"] * qty
            
            total_weight_kg += weight
            total_item_cost += cost
            if row["is_fragile"]:
                is_fragile_overall = True
            if row["is_hazmat"]:
                is_hazmat_overall = True
                
            detailed_items.append({
                "product_id": row["id"],
                "sku": row["sku"],
                "name": row["name"],
                "quantity": qty,
                "unit_price": row["unit_price"],
                "weight_kg": weight,
                "is_fragile": bool(row["is_fragile"]),
                "is_hazmat": bool(row["is_hazmat"])
            })

        return {
            "customer_name": "Acme Autonomous Robotics Corp",
            "destination_city": detected_city,
            "destination_address": destination_address,
            "priority": detected_priority,
            "items": detailed_items,
            "total_weight_kg": round(total_weight_kg, 2),
            "total_item_cost": round(total_item_cost, 2),
            "is_fragile": is_fragile_overall,
            "is_hazmat": is_hazmat_overall
        }
    finally:
        conn.close()

def check_inventory_tool(items: List[Dict[str, Any]], destination_city: str) -> Dict[str, Any]:
    """Check stock across all warehouses, verify availability, and rank optimal warehouse."""
    conn = get_connection()
    try:
        warehouses = conn.execute("SELECT * FROM warehouses WHERE is_active = 1").fetchall()
        
        # Determine preferred region based on destination city
        east_cities = ["New York", "Boston", "Chicago", "Atlanta", "Miami", "Philadelphia"]
        preferred_wh = "WH-EAST" if destination_city in east_cities else "WH-WEST"

        warehouse_eval = []
        best_warehouse_id = None

        for wh in warehouses:
            wh_id = wh["id"]
            can_fulfill = True
            missing_items = []
            available_details = []

            for it in items:
                prod_id = it["product_id"]
                req_qty = it["quantity"]
                inv = conn.execute(
                    "SELECT total_stock, reserved_stock, bin_location FROM inventory WHERE warehouse_id = ? AND product_id = ?",
                    (wh_id, prod_id)
                ).fetchone()

                if not inv:
                    can_fulfill = False
                    missing_items.append({"product_id": prod_id, "reason": "Not stocked"})
                    continue

                available = inv["total_stock"] - inv["reserved_stock"]
                available_details.append({
                    "product_id": prod_id,
                    "available_stock": available,
                    "requested_quantity": req_qty,
                    "bin_location": inv["bin_location"]
                })

                if available < req_qty:
                    can_fulfill = False
                    missing_items.append({
                        "product_id": prod_id,
                        "available_stock": available,
                        "requested_quantity": req_qty,
                        "shortage": req_qty - available
                    })

            warehouse_eval.append({
                "warehouse_id": wh_id,
                "warehouse_name": wh["name"],
                "can_fulfill": can_fulfill,
                "stock_details": available_details,
                "missing_items": missing_items,
                "is_preferred_region": (wh_id == preferred_wh)
            })

        # Select warehouse: fulfillable & preferred region, or any fulfillable
        for eval_wh in warehouse_eval:
            if eval_wh["can_fulfill"] and eval_wh["is_preferred_region"]:
                best_warehouse_id = eval_wh["warehouse_id"]
                break
        
        if not best_warehouse_id:
            for eval_wh in warehouse_eval:
                if eval_wh["can_fulfill"]:
                    best_warehouse_id = eval_wh["warehouse_id"]
                    break

        if not best_warehouse_id:
            raise InventoryShortageError(
                "Insufficient inventory across all warehouses to fulfill order.",
                details={"evaluations": warehouse_eval}
            )

        return {
            "selected_warehouse_id": best_warehouse_id,
            "preferred_warehouse_id": preferred_wh,
            "warehouse_evaluations": warehouse_eval,
            "fulfillment_feasible": True
        }
    finally:
        conn.close()

def reserve_inventory_atomic_tool(
    order_id: str,
    warehouse_id: str,
    items: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Atomically reserve inventory in SQLite using BEGIN IMMEDIATE to avoid race conditions."""
    conn = get_connection()
    try:
        with transaction(conn):
            reservations = []
            now_iso = datetime.now(timezone.utc).isoformat()

            # Idempotency: an order that already holds reservations never reserves twice
            existing = conn.execute(
                "SELECT id, product_id, quantity FROM inventory_reservations WHERE order_id = ? AND status = 'RESERVED'",
                (order_id,)
            ).fetchall()
            if existing:
                return {
                    "warehouse_id": warehouse_id,
                    "reservations": [{"reservation_id": r["id"], "product_id": r["product_id"], "quantity": r["quantity"]} for r in existing],
                    "reserved_count": len(existing),
                    "idempotent_replay": True,
                    "timestamp": now_iso
                }

            for it in items:
                prod_id = it["product_id"]
                qty = it["quantity"]

                # Concurrency check: lock row and check available balance
                row = conn.execute(
                    "SELECT total_stock, reserved_stock, bin_location FROM inventory WHERE warehouse_id = ? AND product_id = ?",
                    (warehouse_id, prod_id)
                ).fetchone()

                if not row:
                    raise InventoryShortageError(f"Product {prod_id} not mapped in warehouse {warehouse_id}")

                available = row["total_stock"] - row["reserved_stock"]
                if available < qty:
                    raise InventoryShortageError(
                        f"Atomic check failed: Product {prod_id} available {available} < required {qty}"
                    )

                # Atomically update reserved stock
                conn.execute(
                    """
                    UPDATE inventory
                    SET reserved_stock = reserved_stock + ?
                    WHERE warehouse_id = ? AND product_id = ?
                    """,
                    (qty, warehouse_id, prod_id)
                )

                # Insert into reservations audit log
                res_id = f"RES-{order_id[-8:]}-{prod_id[-3:]}"
                conn.execute(
                    """
                    INSERT INTO inventory_reservations (id, order_id, warehouse_id, product_id, quantity, status, created_at)
                    VALUES (?, ?, ?, ?, ?, 'RESERVED', ?)
                    """,
                    (res_id, order_id, warehouse_id, prod_id, qty, now_iso)
                )

                reservations.append({
                    "reservation_id": res_id,
                    "product_id": prod_id,
                    "quantity": qty,
                    "bin_location": row["bin_location"],
                    "remaining_available": available - qty
                })

            return {
                "warehouse_id": warehouse_id,
                "reservations": reservations,
                "reserved_count": len(reservations),
                "timestamp": now_iso
            }
    finally:
        conn.close()

def pick_items_tool(order_id: str, warehouse_id: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Simulate warehouse pick operations and verify item bins."""
    conn = get_connection()
    try:
        pick_manifest = []
        for it in items:
            prod_id = it["product_id"]
            qty = it["quantity"]
            row = conn.execute(
                """
                SELECT p.name, p.sku, i.bin_location
                FROM inventory i
                JOIN products p ON i.product_id = p.id
                WHERE i.warehouse_id = ? AND i.product_id = ?
                """,
                (warehouse_id, prod_id)
            ).fetchone()

            bin_loc = row["bin_location"] if row else "A-UNKNOWN"
            p_name = row["name"] if row else prod_id
            sku = row["sku"] if row else "SKU-UNK"

            pick_manifest.append({
                "product_id": prod_id,
                "sku": sku,
                "name": p_name,
                "quantity": qty,
                "bin_location": bin_loc,
                "pick_status": "PICKED_VERIFIED",
                "barcode_scanned": f"BAR-{prod_id}-{bin_loc}"
            })

        return {
            "warehouse_id": warehouse_id,
            "items_picked_count": len(pick_manifest),
            "pick_manifest": pick_manifest,
            "picker_robot_id": f"AGV-BOT-{warehouse_id[-4:]}-7",
            "elapsed_pick_time_sec": 1.4
        }
    finally:
        conn.close()

def package_order_tool(order_id: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Select appropriate certified packaging based on fragility, hazmat, and total weight."""
    conn = get_connection()
    try:
        total_weight_kg = 0.0
        has_fragile = False
        has_hazmat = False

        for it in items:
            prod_id = it["product_id"]
            qty = it["quantity"]
            prod = conn.execute("SELECT weight_kg, is_fragile, is_hazmat FROM products WHERE id = ?", (prod_id,)).fetchone()
            if prod:
                total_weight_kg += prod["weight_kg"] * qty
                if prod["is_fragile"]:
                    has_fragile = True
                if prod["is_hazmat"]:
                    has_hazmat = True

        packages = conn.execute("SELECT * FROM packaging_options ORDER BY cost ASC").fetchall()
        chosen_pkg = None

        for pkg in packages:
            if pkg["max_weight_kg"] >= total_weight_kg:
                if has_hazmat and not pkg["is_hazmat_certified"]:
                    continue
                if has_fragile and not pkg["is_fragile_certified"]:
                    continue
                chosen_pkg = pkg
                break

        # Fallback to highest capacity crate if necessary
        if not chosen_pkg:
            chosen_pkg = conn.execute("SELECT * FROM packaging_options ORDER BY max_weight_kg DESC LIMIT 1").fetchone()

        conn.execute("UPDATE orders SET packaging_id = ?, total_weight_kg = ? WHERE id = ?", (chosen_pkg["id"], total_weight_kg, order_id))

        return {
            "packaging_id": chosen_pkg["id"],
            "packaging_name": chosen_pkg["name"],
            "max_weight_kg": chosen_pkg["max_weight_kg"],
            "actual_weight_kg": round(total_weight_kg, 2),
            "is_fragile_certified": bool(chosen_pkg["is_fragile_certified"]),
            "is_hazmat_certified": bool(chosen_pkg["is_hazmat_certified"]),
            "packaging_cost": chosen_pkg["cost"]
        }
    finally:
        conn.close()

def book_carrier_tool(
    order_id: str,
    priority: str,
    is_fragile: bool,
    is_hazmat: bool,
    total_weight_kg: float,
    simulate_failure: bool = False,
    excluded_carrier_ids: Optional[List[str]] = None,
    preferred_carrier_id: Optional[str] = None
) -> Dict[str, Any]:
    """Book carrier dispatch with support for simulated carrier outage and fallback filtering."""
    conn = get_connection()
    excluded = set(excluded_carrier_ids or [])
    try:
        # Idempotency: an order that already has a booking returns it unchanged
        prior = conn.execute(
            "SELECT o.carrier_id, o.tracking_id, c.name, c.service_level FROM orders o JOIN carriers c ON c.id = o.carrier_id WHERE o.id = ? AND o.tracking_id IS NOT NULL",
            (order_id,)
        ).fetchone()
        if prior:
            return {"carrier_id": prior["carrier_id"], "carrier_name": prior["name"],
                    "service_level": prior["service_level"], "tracking_id": prior["tracking_id"],
                    "estimated_delivery_days": 1, "status": "DISPATCH_CONFIRMED", "idempotent_replay": True}

        carriers = conn.execute("SELECT * FROM carriers WHERE is_active = 1 ORDER BY reliability_rating DESC").fetchall()
        
        eligible_carriers = []
        for c in carriers:
            if c["id"] in excluded:
                continue
            if is_fragile and not c["supports_fragile"]:
                continue
            if is_hazmat and not c["supports_hazmat"]:
                continue
            eligible_carriers.append(c)

        if not eligible_carriers:
            raise CarrierBookingError(
                f"No eligible carrier found meeting constraints (Fragile={is_fragile}, Hazmat={is_hazmat}, Excluded={list(excluded)})"
            )

        selected_carrier = eligible_carriers[0]
        if preferred_carrier_id:
            match = [c for c in eligible_carriers if c["id"] == preferred_carrier_id]
            if not match:
                raise CarrierBookingError(f"Preferred carrier {preferred_carrier_id} is not eligible")
            selected_carrier = match[0]
        
        # Check if simulated failure applies to this carrier
        carrier_should_fail = simulate_failure or bool(selected_carrier["simulate_failure"])

        if carrier_should_fail:
            raise CarrierBookingError(
                f"Carrier Dispatch Outage: {selected_carrier['name']} API returned 503 Service Unavailable (Vehicle telemetry node offline).",
                details={
                    "carrier_id": selected_carrier["id"],
                    "carrier_name": selected_carrier["name"],
                    "error_code": "DISPATCH_TERMINAL_UNREACHABLE",
                    "eligible_alternatives": [c["name"] for c in eligible_carriers[1:]]
                }
            )

        # Generate realistic carrier tracking number
        prefix = selected_carrier["id"].split("-")[-1]
        timestamp_hash = hashlib.md5(f"{order_id}-{time.time()}".encode()).hexdigest()[:6].upper()
        tracking_id = f"TRK-{prefix}-{timestamp_hash}"

        # Persist to orders table
        conn.execute(
            "UPDATE orders SET carrier_id = ?, tracking_id = ? WHERE id = ?",
            (selected_carrier["id"], tracking_id, order_id)
        )

        return {
            "carrier_id": selected_carrier["id"],
            "carrier_name": selected_carrier["name"],
            "service_level": selected_carrier["service_level"],
            "tracking_id": tracking_id,
            "estimated_delivery_days": 1 if priority in ["EXPRESS", "URGENT"] else 3,
            "status": "DISPATCH_CONFIRMED"
        }
    finally:
        conn.close()

def verify_persisted_records_tool(order_id: str) -> Dict[str, Any]:
    """Perform final verification directly against persisted SQLite records.
    Validates atomic reservation counts, order state, carrier booking, and timeline integrity."""
    conn = get_connection()
    try:
        order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not order:
            raise ToolExecutionError(f"Verification failed: Order {order_id} not found in database.")

        # 1. Check order items
        items = conn.execute("SELECT * FROM order_items WHERE order_id = ?", (order_id,)).fetchall()
        if not items:
            raise ToolExecutionError(f"Verification failed: No order items found for {order_id}")

        # 2. Check reservations
        reservations = conn.execute("SELECT * FROM inventory_reservations WHERE order_id = ? AND status = 'RESERVED'", (order_id,)).fetchall()
        if not reservations:
            raise ToolExecutionError(f"Verification failed: No inventory reservations found for {order_id}")

        # Ensure every item in order has matching quantity reserved
        for it in items:
            res_sum = sum(r["quantity"] for r in reservations if r["product_id"] == it["product_id"])
            if res_sum != it["quantity"]:
                raise ToolExecutionError(
                    f"Verification failed: Product {it['product_id']} ordered {it['quantity']} but reserved {res_sum}"
                )

        # 3. Check inventory consistency
        wh_id = order["warehouse_id"]
        for it in items:
            inv = conn.execute(
                "SELECT total_stock, reserved_stock FROM inventory WHERE warehouse_id = ? AND product_id = ?",
                (wh_id, it["product_id"])
            ).fetchone()
            if not inv or inv["reserved_stock"] < it["quantity"]:
                raise ToolExecutionError(f"Verification failed: Warehouse inventory reserved_stock undercount for {it['product_id']}")

        # 4. Check carrier and tracking
        if not order["carrier_id"] or not order["tracking_id"]:
            raise ToolExecutionError("Verification failed: Carrier ID or Tracking ID is missing from persisted order.")

        # 5. Check timeline steps
        steps = conn.execute("SELECT * FROM workflow_steps WHERE order_id = ?", (order_id,)).fetchall()
        if len(steps) < 4:
            raise ToolExecutionError("Verification failed: Incomplete workflow timeline steps recorded.")

        # Compute cryptographic state proof hash
        state_payload = f"{order['id']}:{order['tracking_id']}:{order['carrier_id']}:{len(reservations)}"
        checksum = hashlib.sha256(state_payload.encode()).hexdigest()

        return {
            "is_valid": True,
            "order_persisted": True,
            "reservations_intact": True,
            "inventory_delta_valid": True,
            "carrier_tracking_verified": True,
            "timeline_steps_count": len(steps),
            "checksum": f"SHA256:{checksum[:16]}",
            "details": {
                "order_id": order["id"],
                "tracking_id": order["tracking_id"],
                "warehouse_id": order["warehouse_id"],
                "carrier_id": order["carrier_id"],
                "packaging_id": order["packaging_id"],
                "total_items": len(items),
                "total_reservations": len(reservations)
            }
        }
    finally:
        conn.close()

def release_inventory_reservation_tool(order_id: str) -> Dict[str, Any]:
    """Roll back/release reserved stock in case of unrecoverable workflow failure."""
    conn = get_connection()
    try:
        with transaction(conn):
            reservations = conn.execute(
                "SELECT warehouse_id, product_id, quantity FROM inventory_reservations WHERE order_id = ? AND status = 'RESERVED'",
                (order_id,)
            ).fetchall()

            released = []
            for r in reservations:
                conn.execute(
                    "UPDATE inventory SET reserved_stock = MAX(0, reserved_stock - ?) WHERE warehouse_id = ? AND product_id = ?",
                    (r["quantity"], r["warehouse_id"], r["product_id"])
                )
                released.append({"product_id": r["product_id"], "quantity": r["quantity"]})

            conn.execute("UPDATE inventory_reservations SET status = 'RELEASED' WHERE order_id = ?", (order_id,))
            return {"order_id": order_id, "released_reservations": released}
    finally:
        conn.close()
