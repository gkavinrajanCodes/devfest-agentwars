"""Pydantic data models for Logistics Autopilot."""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum

class OrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VALIDATED = "VALIDATED"
    INVENTORY_CHECKED = "INVENTORY_CHECKED"
    INVENTORY_RESERVED = "INVENTORY_RESERVED"
    ITEMS_PICKED = "ITEMS_PICKED"
    PACKAGED = "PACKAGED"
    CARRIER_BOOKED = "CARRIER_BOOKED"
    VERIFIED = "VERIFIED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"

class StepStatus(str, Enum):
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    FAILED = "FAILED"
    RECOVERED = "RECOVERED"

class OrderItemRequest(BaseModel):
    product_id: str
    quantity: int = Field(gt=0, description="Quantity must be greater than zero")

class OrderItemDetail(BaseModel):
    product_id: str
    product_name: str
    quantity: int
    unit_price: float
    weight_kg: float
    is_fragile: bool
    is_hazmat: bool
    bin_location: Optional[str] = None

class ShipmentCreateRequest(BaseModel):
    raw_prompt: str = Field(..., description="Natural language shipment instruction")
    destination_city: Optional[str] = None
    destination_address: Optional[str] = None
    customer_name: Optional[str] = "Acme Robotics Corp"
    priority: Optional[str] = None
    items: Optional[List[OrderItemRequest]] = None
    idempotency_key: Optional[str] = None
    simulate_carrier_failure: Optional[bool] = False

class WorkflowStepRecord(BaseModel):
    id: Optional[int] = None
    order_id: str
    step_name: str
    tool_name: str
    status: StepStatus
    input_payload: Dict[str, Any]
    output_payload: Dict[str, Any]
    elapsed_ms: int
    timestamp: str

class VerificationResult(BaseModel):
    is_valid: bool
    order_persisted: bool
    reservations_intact: bool
    inventory_delta_valid: bool
    carrier_tracking_verified: bool
    timeline_steps_count: int
    checksum: str
    details: Dict[str, Any]

class OrderDetailResponse(BaseModel):
    id: str
    idempotency_key: Optional[str]
    raw_prompt: str
    customer_name: str
    destination_city: str
    destination_address: str
    priority: str
    status: OrderStatus
    warehouse_id: Optional[str]
    warehouse_name: Optional[str]
    packaging_id: Optional[str]
    packaging_name: Optional[str]
    carrier_id: Optional[str]
    carrier_name: Optional[str]
    tracking_id: Optional[str]
    total_weight_kg: float
    total_cost: float
    failure_reason: Optional[str]
    items: List[OrderItemDetail]
    timeline: List[WorkflowStepRecord]
    verification: Optional[VerificationResult] = None
    report: Optional[Dict[str, Any]] = None
    created_at: str
    updated_at: str

class WarehouseStockInfo(BaseModel):
    warehouse_id: str
    warehouse_name: str
    city: str
    state: str
    product_id: str
    product_name: str
    sku: str
    total_stock: int
    reserved_stock: int
    available_stock: int
    bin_location: str

class CarrierInfo(BaseModel):
    id: str
    name: str
    service_level: str
    reliability_rating: float
    supports_fragile: bool
    supports_hazmat: bool
    is_active: bool
    simulate_failure: bool
