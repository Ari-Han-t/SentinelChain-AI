from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    # Databases differ in how they round-trip timezone offsets. A naive UTC
    # value keeps the exact canonical timestamp stable for audit hashing.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Role(StrEnum):
    ADMIN = "administrator"
    ANALYST = "inventory_analyst"
    MANAGER = "procurement_manager"
    AUDITOR = "auditor"


DEFAULT_CHAIN_KEY = "sentinel-industrial-demo"
DEFAULT_CHAIN_NAME = "Sentinel Industrial Demo"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(40), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    current_stock: Mapped[int] = mapped_column(Integer, default=0)
    unit_cost: Mapped[float] = mapped_column(Float)
    order_cost: Mapped[float] = mapped_column(Float, default=40)
    holding_cost_rate: Mapped[float] = mapped_column(Float, default=0.2)
    lead_time_days: Mapped[int] = mapped_column(Integer, default=7)
    sales: Mapped[list[SaleRecord]] = relationship(back_populates="product", cascade="all, delete-orphan")


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    reliability: Mapped[float] = mapped_column(Float)
    average_lead_time: Mapped[float] = mapped_column(Float)
    defect_rate: Mapped[float] = mapped_column(Float)
    price_variance: Mapped[float] = mapped_column(Float)
    encrypted_contact: Mapped[str] = mapped_column(Text)


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_name: Mapped[str] = mapped_column(String(180))
    digest: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(30))
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    quarantined_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SaleRecord(Base):
    __tablename__ = "sales_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    sold_at: Mapped[date] = mapped_column(Date, index=True)
    quantity: Mapped[float] = mapped_column(Float)
    source_import_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True)
    product: Mapped[Product] = relationship(back_populates="sales")


class QuarantinedRecord(Base):
    __tablename__ = "quarantined_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    import_batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id"), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    payload_json: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Forecast(Base):
    __tablename__ = "forecasts"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    horizon_days: Mapped[int] = mapped_column(Integer)
    daily_demand: Mapped[float] = mapped_column(Float)
    mae: Mapped[float] = mapped_column(Float)
    rmse: Mapped[float] = mapped_column(Float)
    mape: Mapped[float] = mapped_column(Float)
    baseline_mae: Mapped[float] = mapped_column(Float)
    model_name: Mapped[str] = mapped_column(String(80))
    explanation_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    forecast_id: Mapped[int] = mapped_column(ForeignKey("forecasts.id"))
    reorder_point: Mapped[float] = mapped_column(Float)
    safety_stock: Mapped[float] = mapped_column(Float)
    eoq: Mapped[float] = mapped_column(Float)
    recommended_quantity: Mapped[int] = mapped_column(Integer)
    supplier_risk: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(40), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text)
    previous_hash: Mapped[str] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OrganizationProfile(Base):
    __tablename__ = "organization_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    industry: Mapped[str] = mapped_column(String(120), default="Industrial supply")
    description: Mapped[str] = mapped_column(Text, default="")
    objectives_json: Mapped[str] = mapped_column(Text, default="[]")
    constraints_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(30), default="active")
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class UserContext(Base):
    __tablename__ = "user_contexts"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_context_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    owned_stages_json: Mapped[str] = mapped_column(Text, default="[]")
    decision_limits_json: Mapped[str] = mapped_column(Text, default="{}")
    escalation_preferences_json: Mapped[str] = mapped_column(Text, default="{}")
    timezone_name: Mapped[str] = mapped_column(String(80), default="Asia/Calcutta")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# Reusable universal-SCM operating layer.  JSON is deliberately stored as text:
# it keeps the model portable across SQLite (tests) and PostgreSQL deployments.
class NodeTemplate(Base):
    __tablename__ = "node_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    field_definitions_json: Mapped[str] = mapped_column(Text, default="[]")
    enabled_modules_json: Mapped[str] = mapped_column(Text, default="[]")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Workflow(Base):
    __tablename__ = "workflows"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    trigger_json: Mapped[str] = mapped_column(Text, default="{}")
    conditions_json: Mapped[str] = mapped_column(Text, default="[]")
    actions_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkflowExecution(Base):
    __tablename__ = "workflow_executions"
    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    output_json: Mapped[str] = mapped_column(Text, default="{}")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))


class OperationalTask(Base):
    __tablename__ = "operational_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InventoryLot(Base):
    __tablename__ = "inventory_lots"
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), index=True)
    lot_number: Mapped[str] = mapped_column(String(100), index=True)
    quantity: Mapped[float] = mapped_column(Float, default=0)
    location: Mapped[str] = mapped_column(String(160), default="")
    status: Mapped[str] = mapped_column(String(30), default="available", index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StockMovement(Base):
    __tablename__ = "stock_movements"
    id: Mapped[int] = mapped_column(primary_key=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("inventory_lots.id"), index=True)
    movement_type: Mapped[str] = mapped_column(String(30))
    quantity: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_number: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    sku: Mapped[str] = mapped_column(String(64))
    quantity: Mapped[float] = mapped_column(Float)
    unit_cost: Mapped[float] = mapped_column(Float)


class Shipment(Base):
    __tablename__ = "shipments"
    id: Mapped[int] = mapped_column(primary_key=True)
    shipment_number: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    purchase_order_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="planned", index=True)
    carrier: Mapped[str] = mapped_column(String(120), default="")
    tracking_number: Mapped[str] = mapped_column(String(160), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))


class TrackingEvent(Base):
    __tablename__ = "tracking_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    shipment_id: Mapped[int] = mapped_column(ForeignKey("shipments.id"), index=True)
    status: Mapped[str] = mapped_column(String(40))
    location: Mapped[str] = mapped_column(String(160), default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    notes: Mapped[str] = mapped_column(Text, default="")


class QualityInspection(Base):
    __tablename__ = "quality_inspections"
    id: Mapped[int] = mapped_column(primary_key=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("inventory_lots.id"), index=True)
    result: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    quarantine_reason: Mapped[str] = mapped_column(Text, default="")
    disposition: Mapped[str | None] = mapped_column(String(30), nullable=True)
    inspected_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    inspected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Risk(Base):
    __tablename__ = "risks"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    likelihood: Mapped[int] = mapped_column(Integer)
    impact: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    document_type: Mapped[str] = mapped_column(String(60))
    content_digest: Mapped[str] = mapped_column(String(64))
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ControlTowerException(Base):
    __tablename__ = "control_tower_exceptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    severity: Mapped[str] = mapped_column(String(20), default="medium")
    category: Mapped[str] = mapped_column(String(60), default="operational")
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    details: Mapped[str] = mapped_column(Text, default="")
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SupplyChain(Base):
    __tablename__ = "supply_chains"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SupplyChainNode(Base):
    __tablename__ = "supply_chain_nodes"
    __table_args__ = (UniqueConstraint("chain_id", "key", name="uq_supply_chain_node_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    chain_id: Mapped[int] = mapped_column(ForeignKey("supply_chains.id"), index=True)
    key: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(160))
    stage_type: Mapped[str] = mapped_column(String(50), index=True)
    owner_role: Mapped[str] = mapped_column(String(40), default=Role.ANALYST.value)
    position_x: Mapped[float] = mapped_column(Float, default=0)
    position_y: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(30), default="healthy", index=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SupplyChainEdge(Base):
    __tablename__ = "supply_chain_edges"
    __table_args__ = (UniqueConstraint("source_node_id", "target_node_id", name="uq_supply_chain_edge"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_node_id: Mapped[int] = mapped_column(ForeignKey("supply_chain_nodes.id"), index=True)
    target_node_id: Mapped[int] = mapped_column(ForeignKey("supply_chain_nodes.id"), index=True)
    label: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(30), default="healthy")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class EvidenceRecord(Base):
    __tablename__ = "evidence_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("supply_chain_nodes.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(30), index=True)
    external_id: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    summary: Mapped[str] = mapped_column(String(300))
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    integrity_digest: Mapped[str] = mapped_column(String(64), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    status: Mapped[str] = mapped_column(String(30), default="accepted", index=True)
    conflict_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GuidanceRun(Base):
    __tablename__ = "guidance_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("supply_chain_nodes.id"), index=True)
    context_digest: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(40), default="deterministic")
    status_summary: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    evidence_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    no_action_required: Mapped[bool] = mapped_column(Boolean, default=False)
    next_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ActionProposal(Base):
    __tablename__ = "action_proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("supply_chain_nodes.id"), index=True)
    guidance_run_id: Mapped[int | None] = mapped_column(ForeignKey("guidance_runs.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(Text)
    owner_role: Mapped[str] = mapped_column(String(40), index=True)
    urgency: Mapped[str] = mapped_column(String(20), default="normal")
    expected_impact: Mapped[str] = mapped_column(Text, default="")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
