from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, Any]


class ImportRequest(BaseModel):
    dataset_name: str = Field(min_length=1, max_length=180)
    csv_content: str = Field(min_length=1, max_length=5_000_000)
    signature: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


class DecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str = Field(default="", max_length=500)
    expected_status: Literal["pending"] = "pending"


class AttackRequest(BaseModel):
    attack_type: Literal["demand_poisoning", "inventory_manipulation", "supplier_spoofing"]
    sku: str = "SKU-001"


class OrganizationContextRequest(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    industry: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=4000)
    objectives: list[str] = Field(default_factory=list, max_length=20)
    constraints: list[str] = Field(default_factory=list, max_length=20)


class UserContextRequest(BaseModel):
    owned_stages: list[str] = Field(default_factory=list, max_length=30)
    decision_limits: dict[str, Any] = Field(default_factory=dict)
    escalation_preferences: dict[str, Any] = Field(default_factory=dict)
    timezone_name: str = Field(default="Asia/Calcutta", min_length=2, max_length=80)


class EvidenceRequest(BaseModel):
    node_key: str = Field(default="", max_length=80)
    node_id: int | None = None
    chain_id: int | None = None
    event_type: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=300)
    payload: dict[str, Any] = Field(default_factory=dict)
    external_id: str | None = Field(default=None, max_length=160)
    conflict_key: str | None = Field(default=None, max_length=120)
    occurred_at: datetime | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)


class ActionDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str = Field(default="", max_length=1000)
    expected_status: Literal["pending"] = "pending"


class EscalateActionRequest(BaseModel):
    note: str = Field(default="", max_length=1000)


class VerifyNodeRequest(BaseModel):
    note: str = Field(default="", max_length=1000)


class SupplyChainCreateRequest(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,78}[a-z0-9]$", min_length=3, max_length=80)
    name: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=4000)


class SupplyChainUpdateRequest(BaseModel):
    key: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{1,78}[a-z0-9]$", min_length=3, max_length=80)
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=4000)


class NodeCreateRequest(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,78}[a-z0-9]$", min_length=2, max_length=80)
    name: str = Field(min_length=2, max_length=160)
    stage_type: str = Field(default="process", min_length=2, max_length=50)
    owner_role: Literal["administrator", "inventory_analyst", "procurement_manager", "auditor"] = "inventory_analyst"
    position_x: float | None = None
    position_y: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NodeUpdateRequest(BaseModel):
    key: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,78}[a-z0-9]$", min_length=2, max_length=80)
    name: str | None = Field(default=None, min_length=2, max_length=160)
    stage_type: str | None = Field(default=None, min_length=2, max_length=50)
    owner_role: Literal["administrator", "inventory_analyst", "procurement_manager", "auditor"] | None = None
    position_x: float | None = None
    position_y: float | None = None
    metadata: dict[str, Any] | None = None


class EdgeCreateRequest(BaseModel):
    source_node_id: int
    target_node_id: int
    label: str = Field(default="", max_length=120)


class EdgeUpdateRequest(BaseModel):
    label: Optional[str] = Field(default=None, max_length=120)
    source_node_id: Optional[int] = None
    target_node_id: Optional[int] = None


class NodeTemplateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,78}[a-z0-9]$", min_length=3, max_length=80)
    description: str = Field(default="", max_length=4000)
    field_definitions: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    enabled_modules: list[str] = Field(default_factory=list, max_length=50)


class WorkflowRequest(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    trigger: dict[str, Any] = Field(default_factory=dict)
    conditions: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    actions: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    status: Literal["draft", "active", "disabled"] = "draft"


class TaskRequest(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(default="", max_length=4000)
    priority: Literal["low", "normal", "high", "critical"] = "normal"
    assigned_to: int | None = None


class InventoryLotRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    lot_number: str = Field(min_length=1, max_length=100)
    quantity: float = Field(ge=0)
    location: str = Field(default="", max_length=160)


class StockMovementRequest(BaseModel):
    lot_id: int
    movement_type: Literal["receipt", "issue", "adjustment", "transfer"]
    quantity: float = Field(gt=0)
    reason: str = Field(default="", max_length=300)


class PurchaseOrderRequest(BaseModel):
    order_number: str = Field(min_length=1, max_length=80)
    supplier_id: int | None = None
    status: Literal["draft", "submitted", "approved", "closed", "cancelled"] = "draft"
    lines: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


class ShipmentRequest(BaseModel):
    shipment_number: str = Field(min_length=1, max_length=80)
    purchase_order_id: int | None = None
    carrier: str = Field(default="", max_length=120)
    tracking_number: str = Field(default="", max_length=160)


class TrackingEventRequest(BaseModel):
    status: str = Field(min_length=2, max_length=40)
    location: str = Field(default="", max_length=160)
    notes: str = Field(default="", max_length=1000)


class QualityInspectionRequest(BaseModel):
    lot_id: int
    result: Literal["pass", "fail", "pending"]
    quarantine_reason: str = Field(default="", max_length=2000)
    disposition: Literal["release", "scrap", "return", "rework"] | None = None


class RiskRequest(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(default="", max_length=4000)
    likelihood: int = Field(ge=1, le=5)
    impact: int = Field(ge=1, le=5)
    owner_id: int | None = None


class DocumentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    document_type: str = Field(min_length=1, max_length=60)
    content_digest: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExceptionRequest(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    category: str = Field(default="operational", max_length=60)
    details: str = Field(default="", max_length=4000)
    assigned_to: int | None = None
