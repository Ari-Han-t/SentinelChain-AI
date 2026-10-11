"""Management of existing records; governance never replaces operational models."""
from typing import Literal
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .audit import append_audit
from .database import get_db
from .models import (Supplier, Warehouse, Product, InventoryLot, PurchaseOrder,
                     PurchaseOrderLine, Shipment, TrackingEvent, StockMovement,
                     QualityInspection, EntityGovernance, User, Role, SupplyChainNode,
                     EvidenceRecord, GuidanceRun, ActionProposal, Forecast, Recommendation,
                     AuditEvent)
from .security import get_current_user, require_roles, encrypt_field
from .step_policy import CLEARANCE_LEVELS

router = APIRouter(prefix="/entities", tags=["Entity management"])
MODELS = {"suppliers": Supplier, "warehouses": Warehouse, "products": Product,
          "inventory": InventoryLot, "purchase-orders": PurchaseOrder, "shipments": Shipment}


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class SupplierInput(StrictInput):
    name: str = Field(min_length=2, max_length=160)
    reliability: float = Field(ge=0, le=1)
    average_lead_time: float = Field(ge=0, le=3650)
    defect_rate: float = Field(ge=0, le=1)
    price_variance: float = Field(ge=0, le=1)
    contact: str | None = Field(default=None, max_length=1000)


class WarehouseInput(StrictInput):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=2, max_length=160)
    location: str = Field(default="", max_length=160)


class ProductInput(StrictInput):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=2, max_length=160)
    current_stock: int = Field(ge=0, le=1_000_000_000)
    unit_cost: float = Field(gt=0, le=1_000_000_000)
    order_cost: float = Field(default=40, gt=0)
    holding_cost_rate: float = Field(default=.2, gt=0, le=1)
    lead_time_days: int = Field(default=7, ge=1, le=3650)


class InventoryInput(StrictInput):
    sku: str = Field(min_length=1, max_length=64)
    lot_number: str = Field(min_length=1, max_length=100)
    quantity: float = Field(ge=0, le=1_000_000_000)
    location: str = Field(default="", max_length=160)


class LineInput(StrictInput):
    sku: str = Field(min_length=1, max_length=64)
    quantity: float = Field(gt=0, le=1_000_000_000)
    unit_cost: float = Field(ge=0, le=1_000_000_000)


class OrderInput(StrictInput):
    order_number: str = Field(min_length=1, max_length=80)
    supplier_id: int | None = Field(default=None, gt=0)
    lines: list[LineInput] = Field(min_length=1, max_length=100)


class ShipmentInput(StrictInput):
    shipment_number: str = Field(min_length=1, max_length=80)
    purchase_order_id: int | None = Field(default=None, gt=0)
    carrier: str = Field(default="", max_length=120)
    tracking_number: str = Field(default="", max_length=160)


INPUTS = {"suppliers": SupplierInput, "warehouses": WarehouseInput, "products": ProductInput,
          "inventory": InventoryInput, "purchase-orders": OrderInput, "shipments": ShipmentInput}


class GovernanceInput(StrictInput):
    owner_id: int | None = Field(default=None, gt=0)
    stage_id: int | None = Field(default=None, gt=0)
    warehouse_id: int | None = Field(default=None, gt=0)
    risk_level: Literal["low", "medium", "high", "critical"] = "low"
    minimum_clearance: int = Field(default=1, ge=1, le=4)


class EntityInput(StrictInput):
    data: dict
    governance: GovernanceInput = Field(default_factory=GovernanceInput)
    expected_version: int | None = Field(default=None, ge=1)
    reason: str = Field(min_length=3, max_length=1000)


class StateInput(StrictInput):
    active: bool
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=1000)


def model_for(kind):
    if kind not in MODELS:
        raise HTTPException(404, "Unknown entity type")
    return MODELS[kind]


def governance_for(db, kind, entity_id):
    return db.scalar(select(EntityGovernance).where(EntityGovernance.kind == kind, EntityGovernance.entity_id == entity_id))


def accessible(db, user, kind, entity_id, operational=False):
    governance = governance_for(db, kind, entity_id)
    from .policies import entity_level
    if CLEARANCE_LEVELS.get(user.role, 0) < max(entity_level(db, kind), governance.minimum_clearance if governance else 1):
        return False
    if operational and governance and not governance.active:
        return False
    # A child cannot expose or operate on a more restricted parent.
    item = db.get(MODELS[kind], entity_id)
    if item is None:
        return False
    parents = []
    if kind == "inventory":
        product = db.scalar(select(Product).where(Product.sku == item.sku))
        if product:
            parents.append(("products", product.id))
        if governance and governance.warehouse_id:
            parents.append(("warehouses", governance.warehouse_id))
    if kind == "purchase-orders":
        if item.supplier_id:
            parents.append(("suppliers", item.supplier_id))
        for sku in db.scalars(select(PurchaseOrderLine.sku).where(PurchaseOrderLine.purchase_order_id == entity_id)):
            product = db.scalar(select(Product).where(Product.sku == sku))
            if product:
                parents.append(("products", product.id))
    if kind == "shipments" and item.purchase_order_id:
        parents.append(("purchase-orders", item.purchase_order_id))
    return all(accessible(db, user, parent_kind, parent_id, operational) for parent_kind, parent_id in parents)


def guard(db, user, kind, entity_id, operational=False):
    if not accessible(db, user, kind, entity_id):
        append_audit(db, "entity.access_denied", user.id, {"kind":kind,"entity_id":entity_id,"outcome":"denied"})
        db.commit()
        raise HTTPException(403, "Entity clearance requirement is not met")
    if operational and not accessible(db, user, kind, entity_id, True):
        raise HTTPException(409, "Entity is deactivated")


def dump(item):
    # Never serialize encrypted contacts or key material into responses/audits.
    return {c.name: getattr(item, c.name) for c in item.__table__.columns if c.name != "encrypted_contact"}


def entity_json(db, kind, item):
    data = dump(item)
    if kind == "suppliers":
        from .analytics import supplier_risk
        data["risk_score"] = supplier_risk(item.reliability, item.average_lead_time, item.defect_rate, item.price_variance)
    if kind == "purchase-orders":
        data["lines"] = [dump(x) for x in db.scalars(select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == item.id))]
    governance = governance_for(db, kind, item.id)
    labels = {}
    if governance:
        for key, model, label in (("owner_id", User, "display_name"), ("stage_id", SupplyChainNode, "name"), ("warehouse_id", Warehouse, "name")):
            target_id = getattr(governance, key)
            target = db.get(model, target_id) if target_id else None
            if target is not None:
                labels[key] = getattr(target, label)
    return {"id": item.id, "kind": kind, "data": data, "governance_labels": labels,
            "governance": {k: getattr(governance, k) for k in GovernanceInput.model_fields} if governance else GovernanceInput().model_dump(),
            "active": governance.active if governance else True,
            "version": governance.version if governance else 1}


def entity_or_404(db, kind, entity_id):
    item = db.get(model_for(kind), entity_id)
    if item is None:
        raise HTTPException(404, "Entity not found")
    return item


@router.get("/users")
def assignable_users(user: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)):
    return [{"id": u.id, "display_name": u.display_name, "role": u.role} for u in db.scalars(select(User))]


@router.get("/{kind}")
def list_entities(kind: str, q: str = Query(default="", max_length=160),
                  status: Literal["all", "active", "inactive"] = "all",
                  sort: Literal["name", "id", "risk"] = "name",
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = [entity_json(db, kind, x) for x in db.scalars(select(model_for(kind))) if accessible(db, user, kind, x.id)]
    if status != "all":
        rows = [r for r in rows if r["active"] == (status == "active")]
    if q:
        rows = [r for r in rows if q.casefold() in " ".join(str(v) for v in r["data"].values()).casefold()]
    risks = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    rows.sort(key=lambda r: r["id"] if sort == "id" else -risks[r["governance"]["risk_level"]] if sort == "risk" else str(r["data"].get("name", r["data"].get("sku", r["data"].get("order_number", r["data"].get("shipment_number", r["data"].get("lot_number", "")))))).casefold())
    return rows


def validate_references(db, user, kind, data, governance):
    for key, model in (("owner_id", User), ("stage_id", SupplyChainNode), ("warehouse_id", Warehouse)):
        value = getattr(governance, key)
        if value is not None:
            record = db.get(model, value)
            if record is None or (key == "stage_id" and not record.active):
                raise HTTPException(422, f"Invalid {key}")
            if key == "warehouse_id":
                guard(db, user, "warehouses", value, True)
    for field, related_kind in (("supplier_id", "suppliers"), ("purchase_order_id", "purchase-orders")):
        value = data.get(field)
        if value is not None:
            entity_or_404(db, related_kind, value)
            guard(db, user, related_kind, value, True)
    skus = [data["sku"]] if kind == "inventory" else [line["sku"] for line in data.get("lines", [])]
    for sku in skus:
        product = db.scalar(select(Product).where(Product.sku == sku))
        if product is None:
            raise HTTPException(422, f"Unknown product SKU: {sku}")
        guard(db, user, "products", product.id, True)


def save_entity(db, user, kind, body, item=None, *, commit=True):
    model_for(kind)
    if body.governance.warehouse_id is not None and kind != "inventory":
        raise HTTPException(422, "Warehouse assignment applies only to inventory lots")
    try:
        data = INPUTS[kind].model_validate(body.data).model_dump()
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_url=False, include_context=False)) from exc
    validate_references(db, user, kind, data, body.governance)
    before = entity_json(db, kind, item) if item else None
    governance = governance_for(db, kind, item.id) if item else None
    if item:
        guard(db, user, kind, item.id, True)
        if body.expected_version is None or body.expected_version != (governance.version if governance else 1):
            raise HTTPException(409, "Record changed; reload before saving")
        if kind == "inventory" and item.status == "quarantined" and data["quantity"] != item.quantity:
            raise HTTPException(409, "Quarantined stock cannot be adjusted here")
        if kind == "purchase-orders" and item.status != "draft":
            raise HTTPException(409, "Only draft purchase orders can be edited")
        if kind in ("products", "inventory") and data["sku"] != item.sku:
            raise HTTPException(409, "Existing SKU cannot be changed")
    from .policies import enforce
    if kind == "suppliers":
        enforce(db, user, "supplier.update", risk=body.governance.risk_level if item is None else max((body.governance.risk_level, entity_risk(db, kind, item.id)), key={"low":0,"medium":1,"high":2,"critical":3}.get))
    if kind == "inventory":
        delta = data["quantity"] - (item.quantity if item is not None else 0)
        enforce(db, user, "inventory.change", risk=body.governance.risk_level if item is None else max((body.governance.risk_level, entity_risk(db, kind, item.id)), key={"low":0,"medium":1,"high":2,"critical":3}.get), quantity_delta=delta)
    if kind == "products" and (item is None or data["current_stock"] != item.current_stock):
        delta = data["current_stock"] - (item.current_stock if item is not None else 0)
        enforce(db, user, "inventory.change", risk=body.governance.risk_level if item is None else max((body.governance.risk_level, entity_risk(db, kind, item.id)), key={"low":0,"medium":1,"high":2,"critical":3}.get), quantity_delta=delta)
    contact = data.pop("contact", None)
    lines = data.pop("lines", None)
    if item is None:
        item = MODELS[kind](**data)
        if hasattr(item, "created_by"):
            item.created_by = user.id
        if kind == "suppliers":
            item.encrypted_contact = encrypt_field(contact or "")
        db.add(item)
    else:
        for key, value in data.items():
            setattr(item, key, value)
    if kind == "suppliers" and contact is not None:
        item.encrypted_contact = encrypt_field(contact)
    try:
        db.flush()
        if governance is None:
            governance = EntityGovernance(kind=kind, entity_id=item.id, version=1)
            db.add(governance)
        if before:
            governance.version += 1
        for key, value in body.governance.model_dump().items():
            setattr(governance, key, value)
        if lines is not None:
            for line in db.scalars(select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == item.id)):
                db.delete(line)
            for line in lines:
                db.add(PurchaseOrderLine(purchase_order_id=item.id, **line))
        if before and kind == "inventory" and before["data"]["quantity"] != item.quantity:
            db.add(StockMovement(lot_id=item.id, movement_type="adjustment", quantity=item.quantity-before["data"]["quantity"], reason=body.reason, created_by=user.id))
        db.flush()
        after = entity_json(db, kind, item)
        append_audit(db, "entity.updated" if before else "entity.created", user.id,
                     {"kind": kind, "entity_id": item.id, "before": before, "after": after, "reason": body.reason, "contact_updated": contact is not None if kind == "suppliers" else False})
        if commit:
            db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Identifier already exists or a related record changed; reload and retry") from exc
    return after


@router.post("/{kind}", status_code=201)
def create_entity(kind: str, body: EntityInput, user: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)):
    return save_entity(db, user, kind, body)


@router.put("/{kind}/{entity_id}")
def update_entity(kind: str, entity_id: int, body: EntityInput, user: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)):
    # Row locks serialize concurrent changes on PostgreSQL.
    model = model_for(kind)
    db.scalar(select(model).where(model.id == entity_id).with_for_update())
    return save_entity(db, user, kind, body, entity_or_404(db, kind, entity_id))


@router.post("/{kind}/{entity_id}/state")
def set_entity_state(kind: str, entity_id: int, body: StateInput, user: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)):
    model = model_for(kind)
    db.scalar(select(model).where(model.id == entity_id).with_for_update())
    item = entity_or_404(db, kind, entity_id)
    before = entity_json(db, kind, item)
    if before["version"] != body.expected_version:
        raise HTTPException(409, "Record changed; reload before saving")
    from .policies import enforce
    if kind == "suppliers":
        enforce(db, user, "supplier.update", risk=entity_risk(db, kind, entity_id))
    governance = governance_for(db, kind, entity_id)
    if governance is None:
        governance = EntityGovernance(kind=kind, entity_id=entity_id, version=1)
        db.add(governance)
    governance.active = body.active
    governance.version += 1
    db.flush()
    after = entity_json(db, kind, item)
    append_audit(db, "entity.activated" if body.active else "entity.deactivated", user.id,
                 {"kind": kind, "entity_id": entity_id, "before": before, "after": after, "reason": body.reason})
    db.commit()
    return after


@router.get("/{kind}/{entity_id}")
def entity_detail(kind: str, entity_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = entity_or_404(db, kind, entity_id)
    guard(db, user, kind, entity_id)
    result = entity_json(db, kind, item)
    related = {}
    governance = governance_for(db, kind, entity_id)
    if governance and governance.stage_id:
        stage = db.get(SupplyChainNode, governance.stage_id)
        related["stage"] = [dump(stage)] if stage else []
        related["evidence"] = [dump(x) for x in db.scalars(select(EvidenceRecord).where(EvidenceRecord.node_id == governance.stage_id))]
        related["guidance"] = [dump(x) for x in db.scalars(select(GuidanceRun).where(GuidanceRun.node_id == governance.stage_id).order_by(GuidanceRun.id.desc()).limit(20))]
        related["approvals"] = [dump(x) for x in db.scalars(select(ActionProposal).where(ActionProposal.node_id == governance.stage_id))]
    if kind == "suppliers":
        related["purchase_orders"] = [dump(x) for x in db.scalars(select(PurchaseOrder).where(PurchaseOrder.supplier_id == entity_id)) if accessible(db, user, "purchase-orders", x.id)]
    if kind == "purchase-orders":
        related["shipments"] = [dump(x) for x in db.scalars(select(Shipment).where(Shipment.purchase_order_id == entity_id)) if accessible(db, user, "shipments", x.id)]
    if kind == "shipments":
        related["tracking"] = [dump(x) for x in db.scalars(select(TrackingEvent).where(TrackingEvent.shipment_id == entity_id))]
    if kind == "warehouses":
        related["inventory"] = [entity_json(db, "inventory", entity_or_404(db, "inventory", g.entity_id)) for g in db.scalars(select(EntityGovernance).where(EntityGovernance.warehouse_id == entity_id, EntityGovernance.kind == "inventory")) if accessible(db, user, "inventory", g.entity_id)]
    if kind == "inventory":
        related["movements"] = [dump(x) for x in db.scalars(select(StockMovement).where(StockMovement.lot_id == entity_id))]
        related["quality_inspections"] = [dump(x) for x in db.scalars(select(QualityInspection).where(QualityInspection.lot_id == entity_id))]
    product = item if kind == "products" else db.scalar(select(Product).where(Product.sku == item.sku)) if kind == "inventory" else None
    if product and accessible(db, user, "products", product.id):
        related["forecasts"] = [dump(x) for x in db.scalars(select(Forecast).where(Forecast.product_id == product.id))]
        related["recommendations"] = [dump(x) for x in db.scalars(select(Recommendation).where(Recommendation.product_id == product.id))]
    # Existing alerts have no entity FK; do not falsely attribute global incidents.
    result["related"] = related
    result["audit"] = []
    if user.role in (Role.ADMIN.value, Role.AUDITOR.value):
        for event in db.scalars(select(AuditEvent).order_by(AuditEvent.sequence.desc())):
            payload = json.loads(event.payload_json)
            matches = payload.get("kind") == kind and payload.get("entity_id") == entity_id
            if kind == "inventory":
                matches |= payload.get("lot_id") == entity_id or (event.event_type == "inventory.lot_created" and payload.get("id") == entity_id)
            elif kind == "purchase-orders":
                matches |= event.event_type == "purchase_order.created" and payload.get("id") == entity_id
            elif kind == "shipments":
                matches |= payload.get("shipment_id") == entity_id or (event.event_type == "shipment.created" and payload.get("id") == entity_id)
            elif kind == "products":
                matches |= event.event_type in ("forecast.trained", "recommendation.generated") and payload.get("sku") == item.sku
            if matches:
                result["audit"].append({"sequence": event.sequence, "event_type": event.event_type, "actor_id": event.actor_id, "created_at": event.created_at, "reason": payload.get("reason")})
    return result


def bump_version(db, kind, entity_id):
    governance = governance_for(db, kind, entity_id)
    if governance is not None:
        governance.version += 1
    else:
        db.add(EntityGovernance(kind=kind, entity_id=entity_id, version=2))


def entity_risk(db, kind, entity_id):
    governance = governance_for(db, kind, entity_id)
    return governance.risk_level if governance else "low"
