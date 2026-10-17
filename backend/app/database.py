"""Database management and SQLite schema for Logistics Autopilot."""
import sqlite3
import os
import json
from contextlib import contextmanager

DB_PATH = os.environ.get("LOGISTICS_DB_PATH", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logistics.db")))

def get_connection():
    """Get a SQLite connection with row factory enabled."""
    db_file = os.environ.get("LOGISTICS_DB_PATH", DB_PATH)
    conn = sqlite3.connect(db_file, timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

@contextmanager
def transaction(conn=None):
    """Context manager for atomic transaction using BEGIN IMMEDIATE for write safety."""
    should_close = False
    if conn is None:
        conn = get_connection()
        should_close = True
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        if should_close:
            conn.close()

def init_db():
    """Create all required tables and indexes if they do not exist."""
    conn = get_connection()
    try:
        with conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS warehouses (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                city TEXT NOT NULL,
                state TEXT NOT NULL,
                zip_code TEXT NOT NULL,
                region TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                sku TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                weight_kg REAL NOT NULL,
                dimensions_cm TEXT NOT NULL,
                is_fragile INTEGER NOT NULL DEFAULT 0,
                is_hazmat INTEGER NOT NULL DEFAULT 0,
                unit_price REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                warehouse_id TEXT NOT NULL REFERENCES warehouses(id),
                product_id TEXT NOT NULL REFERENCES products(id),
                total_stock INTEGER NOT NULL DEFAULT 0,
                reserved_stock INTEGER NOT NULL DEFAULT 0,
                bin_location TEXT NOT NULL,
                UNIQUE(warehouse_id, product_id)
            );

            CREATE TABLE IF NOT EXISTS packaging_options (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                max_weight_kg REAL NOT NULL,
                is_fragile_certified INTEGER NOT NULL DEFAULT 0,
                is_hazmat_certified INTEGER NOT NULL DEFAULT 0,
                cost REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS carriers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                service_level TEXT NOT NULL,
                reliability_rating REAL NOT NULL,
                supports_fragile INTEGER NOT NULL DEFAULT 1,
                supports_hazmat INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                simulate_failure INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                idempotency_key TEXT UNIQUE,
                raw_prompt TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                destination_city TEXT NOT NULL,
                destination_address TEXT NOT NULL,
                priority TEXT NOT NULL,
                status TEXT NOT NULL,
                warehouse_id TEXT REFERENCES warehouses(id),
                packaging_id TEXT REFERENCES packaging_options(id),
                carrier_id TEXT REFERENCES carriers(id),
                tracking_id TEXT,
                total_weight_kg REAL DEFAULT 0.0,
                total_cost REAL DEFAULT 0.0,
                failure_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                product_id TEXT NOT NULL REFERENCES products(id),
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS inventory_reservations (
                id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                warehouse_id TEXT NOT NULL REFERENCES warehouses(id),
                product_id TEXT NOT NULL REFERENCES products(id),
                quantity INTEGER NOT NULL,
                status TEXT NOT NULL, -- RESERVED, COMMITTED, RELEASED
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS workflow_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                step_name TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                status TEXT NOT NULL, -- SUCCESS, WARNING, FAILED, RECOVERED
                input_payload TEXT,
                output_payload TEXT,
                elapsed_ms INTEGER NOT NULL DEFAULT 0,
                timestamp TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_inventory_lookup ON inventory(warehouse_id, product_id);
            CREATE INDEX IF NOT EXISTS idx_workflow_order ON workflow_steps(order_id);
            CREATE INDEX IF NOT EXISTS idx_reservations_order ON inventory_reservations(order_id);
            """)
    finally:
        conn.close()

def seed_db():
    """Populate warehouses, products, inventory, packaging and carriers."""
    conn = get_connection()
    try:
        with transaction(conn):
            # 1. Warehouses
            warehouses = [
                ("WH-EAST", "Alpha Hub (East Coast)", "Newark", "NJ", "07101", "EAST", 1),
                ("WH-WEST", "Beta Hub (West Coast)", "Oakland", "CA", "94607", "WEST", 1)
            ]
            conn.executemany("""
                INSERT OR REPLACE INTO warehouses (id, name, city, state, zip_code, region, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, warehouses)

            # 2. Products
            products = [
                ("PROD-001", "SKU-LDR-900", "Industrial LiDAR Scanner", "Solid-state autonomous navigation sensor", 1.4, "22x14x10", 1, 0, 1250.0),
                ("PROD-002", "SKU-THM-450", "Thermal Imaging Core", "High-sensitivity infrared sensor module", 0.7, "16x11x8", 1, 0, 890.0),
                ("PROD-003", "SKU-BAT-48V", "Solid-State Battery Pack 48V", "UN3480 certified aerospace lithium module", 4.2, "30x20x15", 0, 1, 640.0),
                ("PROD-004", "SKU-SRV-200", "Precision Servo Actuator", "Ultra-low backlash robotic joint actuator", 2.1, "18x12x12", 0, 0, 310.0),
            ]
            conn.executemany("""
                INSERT OR REPLACE INTO products (id, sku, name, description, weight_kg, dimensions_cm, is_fragile, is_hazmat, unit_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, products)

            # 3. Packaging
            packages = [
                ("PKG-STD-M", "Standard Eco Box (Medium)", 5.0, 0, 0, 4.50),
                ("PKG-FRG-S", "Padded Foam Casket (Fragile Certified)", 3.5, 1, 0, 14.00),
                ("PKG-HAZ-L", "Reinforced Hazmat Drum (DOT Certified)", 15.0, 0, 1, 28.00),
                ("PKG-HVY-XL", "Heavy-Duty Wooden Pallet Crate", 50.0, 1, 1, 45.00),
            ]
            conn.executemany("""
                INSERT OR REPLACE INTO packaging_options (id, name, max_weight_kg, is_fragile_certified, is_hazmat_certified, cost)
                VALUES (?, ?, ?, ?, ?, ?)
            """, packages)

            # 4. Carriers
            carriers = [
                ("CARRIER-APEX", "Apex Express Air", "Express", 4.92, 1, 0, 1, 0),
                ("CARRIER-SWIFT", "SwiftHaul Logistics", "Standard/Express", 4.85, 1, 1, 1, 0),
                ("CARRIER-TITAN", "Titan Heavy Freight", "Ground/Hazmat", 4.70, 0, 1, 1, 0),
            ]
            conn.executemany("""
                INSERT OR REPLACE INTO carriers (id, name, service_level, reliability_rating, supports_fragile, supports_hazmat, is_active, simulate_failure)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, carriers)

            # 5. Inventory default stock (50 each for WH-EAST, 40 each for WH-WEST)
            inventory_seed = [
                ("WH-EAST", "PROD-001", 50, 0, "A-12-01"),
                ("WH-EAST", "PROD-002", 50, 0, "A-14-03"),
                ("WH-EAST", "PROD-003", 40, 0, "H-02-01"),
                ("WH-EAST", "PROD-004", 60, 0, "B-05-02"),
                ("WH-WEST", "PROD-001", 40, 0, "W-01-04"),
                ("WH-WEST", "PROD-002", 40, 0, "W-02-02"),
                ("WH-WEST", "PROD-003", 35, 0, "W-HZ-01"),
                ("WH-WEST", "PROD-004", 45, 0, "W-08-03"),
            ]
            conn.executemany("""
                INSERT OR REPLACE INTO inventory (warehouse_id, product_id, total_stock, reserved_stock, bin_location)
                VALUES (?, ?, ?, ?, ?)
            """, inventory_seed)
    finally:
        conn.close()

def reset_demo_database():
    """Deterministic demo reset: clears active orders, reservations, timeline logs, and resets inventory to initial state."""
    conn = get_connection()
    try:
        with transaction(conn):
            conn.execute("DELETE FROM workflow_steps")
            conn.execute("DELETE FROM inventory_reservations")
            conn.execute("DELETE FROM order_items")
            conn.execute("DELETE FROM orders")
            # Reset reserved stock to 0 and restore base total stock
            conn.execute("UPDATE inventory SET reserved_stock = 0")
            conn.execute("UPDATE inventory SET total_stock = 50 WHERE warehouse_id = 'WH-EAST' AND product_id IN ('PROD-001', 'PROD-002')")
            conn.execute("UPDATE inventory SET total_stock = 40 WHERE warehouse_id = 'WH-EAST' AND product_id = 'PROD-003'")
            conn.execute("UPDATE inventory SET total_stock = 60 WHERE warehouse_id = 'WH-EAST' AND product_id = 'PROD-004'")
            conn.execute("UPDATE inventory SET total_stock = 40 WHERE warehouse_id = 'WH-WEST' AND product_id IN ('PROD-001', 'PROD-002')")
            conn.execute("UPDATE inventory SET total_stock = 35 WHERE warehouse_id = 'WH-WEST' AND product_id = 'PROD-003'")
            conn.execute("UPDATE inventory SET total_stock = 45 WHERE warehouse_id = 'WH-WEST' AND product_id = 'PROD-004'")
            # Reset simulated failure flags
            conn.execute("UPDATE carriers SET simulate_failure = 0")
    finally:
        conn.close()
