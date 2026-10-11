from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from ..entities import SupplierInput, WarehouseInput, ProductInput, InventoryInput, LineInput

System = Literal["erp", "inventory", "supplier", "logistics"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class SupplierData(SupplierInput):
    compliance_status: Literal["unknown", "pending", "compliant", "non_compliant"] = "unknown"
    identity_status: Literal["unverified", "verified", "disputed"] = "unverified"


class InventoryData(InventoryInput):
    warehouse_external_id: str | None = Field(default=None, max_length=120)


class OrderData(Strict):
    order_number: str = Field(min_length=1, max_length=80)
    supplier_external_id: str | None = Field(default=None, max_length=120)
    lines: list[LineInput] = Field(min_length=1, max_length=100)


class ShipmentData(Strict):
    shipment_number: str = Field(min_length=1, max_length=80)
    purchase_order_external_id: str | None = Field(default=None, max_length=120)
    carrier: str = Field(default="", max_length=120)
    tracking_number: str = Field(default="", max_length=160)
    reported_status: Literal["planned", "in_transit", "delivered", "delayed", "exception"] = "planned"
    estimated_arrival: datetime | None = None

    @model_validator(mode="after")
    def valid(self):
        if self.estimated_arrival is not None and self.estimated_arrival.tzinfo is None:
            raise ValueError("Estimated arrival must include a timezone")
        return self


class MovementData(Strict):
    lot_external_id: str = Field(min_length=1, max_length=120)
    movement_type: Literal["receipt", "issue", "transfer", "adjustment"]
    quantity: float = Field(gt=0, le=1000000000)
    reason: str = Field(min_length=3, max_length=300)


class TrackingData(Strict):
    shipment_external_id: str = Field(min_length=1, max_length=120)
    status: Literal["planned", "in_transit", "delivered", "delayed", "exception"]
    location: str = Field(default="", max_length=160)
    notes: str = Field(default="", max_length=1000)


DATA_SCHEMAS = {"suppliers": SupplierData, "warehouses": WarehouseInput, "products": ProductInput,
                "inventory": InventoryData, "purchase-orders": OrderData, "shipments": ShipmentData,
                "stock-movements": MovementData, "tracking-events": TrackingData}
RESOURCES = {"erp": {"suppliers", "products", "purchase-orders"}, "inventory": {"warehouses", "inventory", "stock-movements"},
             "supplier": {"suppliers"}, "logistics": {"shipments", "tracking-events"}}


class ExternalRecord(Strict):
    event_id: str = Field(min_length=1, max_length=120)
    external_id: str = Field(min_length=1, max_length=120)
    resource: Literal["suppliers", "warehouses", "products", "inventory", "purchase-orders", "shipments", "stock-movements", "tracking-events"]
    source_version: int = Field(ge=1, le=2147483647, strict=True)
    occurred_at: datetime
    data: dict

    @model_validator(mode="after")
    def valid(self):
        if self.occurred_at.tzinfo is None:
            raise ValueError("Source timestamps must include a timezone")
        self.data = DATA_SCHEMAS[self.resource].model_validate(self.data).model_dump(mode="json")
        return self


class Page(Strict):
    records: list[ExternalRecord] = Field(max_length=200)
    next_cursor: str | None = Field(default=None, max_length=256)


class Profile(Strict):
    system: System
    base_url: str = Field(max_length=500)
    token_env: str = Field(pattern=r"^SENTINEL_INTEGRATION_[A-Z0-9_]+_TOKEN$")
    timeout_seconds: int = Field(default=10, ge=1, le=10)
    max_attempts: int = Field(default=3, ge=1, le=3)


class ConnectionInput(Strict):
    name: str = Field(min_length=2, max_length=120)
    system: System
    mode: Literal["mock", "live"] = "mock"
    profile: str | None = Field(default=None, max_length=80)
    enabled: bool = False
    mock_scenario: Literal["healthy", "transient", "rate_limited", "invalid"] = "healthy"
    stale_after_seconds: int = Field(default=3600, ge=60, le=604800)
    reason: str = Field(min_length=3, max_length=1000)

    @model_validator(mode="after")
    def valid(self):
        if self.mode == "live" and not self.profile:
            raise ValueError("Live connections require a backend profile")
        if self.mode == "mock" and self.profile:
            raise ValueError("Mock connections cannot use credentials or live profiles")
        if self.mode == "live" and self.mock_scenario != "healthy":
            raise ValueError("Mock scenarios cannot be used with live connections")
        return self


class StateInput(Strict):
    enabled: bool
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=1000)


class RunInput(Strict):
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    reason: str = Field(min_length=3, max_length=1000)


class ApplyInput(Strict):
    expected_source_version: int = Field(ge=1)
    target_entity_id: int | None = Field(default=None, gt=0)
    expected_entity_version: int | None = Field(default=None, ge=1)
    parent_entity_id: int | None = Field(default=None, gt=0)
    reason: str = Field(min_length=3, max_length=1000)
