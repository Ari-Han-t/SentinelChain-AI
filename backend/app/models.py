from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
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
