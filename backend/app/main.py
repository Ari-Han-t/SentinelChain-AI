from __future__ import annotations

import hashlib
import json
import time
import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .analytics import DatasetError, analyze_sales, inventory_policy, parse_sales_csv, supplier_risk, train_forecast
from .audit import append_audit, verify_chain
from .config import settings
from .database import SessionLocal, get_db, init_db
from .guidance import context_digest, guidance_for, utc_after
from .models import (
    ActionProposal,
    Alert,
    AuditEvent,
    EvidenceRecord,
    Forecast,
    GuidanceRun,
    ImportBatch,
    OrganizationProfile,
    Product,
    QuarantinedRecord,
    Recommendation,
    Role,
    SaleRecord,
    Supplier,
    SupplyChain,
    SupplyChainEdge,
    SupplyChainNode,
    User,
    UserContext,
    NodeTemplate, Workflow, WorkflowExecution, OperationalTask, InventoryLot, StockMovement,
    PurchaseOrder, PurchaseOrderLine, Shipment, TrackingEvent, QualityInspection, Risk, Document,
    ControlTowerException,
    utcnow,
)
from .schemas import (
    ActionDecisionRequest,
    AttackRequest,
    DecisionRequest,
    EdgeCreateRequest,
    EdgeUpdateRequest,
    EscalateActionRequest,
    EvidenceRequest,
    ImportRequest,
    LoginRequest,
    NodeCreateRequest,
    NodeUpdateRequest,
    OrganizationContextRequest,
    SupplyChainCreateRequest,
    SupplyChainUpdateRequest,
    TokenResponse,
    UserContextRequest,
    VerifyNodeRequest,
    NodeTemplateRequest, WorkflowRequest, TaskRequest, InventoryLotRequest, StockMovementRequest,
    PurchaseOrderRequest, ShipmentRequest, TrackingEventRequest, QualityInspectionRequest,
    RiskRequest, DocumentRequest, ExceptionRequest,
)
from .security import create_access_token, get_current_user, permissions_for, require_roles, sign_import, verify_import_signature, verify_password
from .seed import bootstrap_admin, seed_database
from .step_policy import clearance_matrix, step_spec


async def _monitoring_loop() -> None:
    while True:
        await asyncio.sleep(max(settings.monitoring_interval_seconds, 60))
        with SessionLocal() as db:
            nodes = db.scalars(select(SupplyChainNode).where(SupplyChainNode.active.is_(True))).all()
            for node in nodes:
                latest = db.scalar(select(GuidanceRun).where(GuidanceRun.node_id == node.id).order_by(GuidanceRun.created_at.desc()).limit(1))
                if latest is None or latest.next_check_at <= datetime.now(timezone.utc).replace(tzinfo=None):
                    _run_node_guidance(db, node, None, force=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if settings.seed_demo_data:
        seed_database()
    elif settings.bootstrap_admin_email and settings.bootstrap_admin_password:
        bootstrap_admin(settings.bootstrap_admin_email, settings.bootstrap_admin_password)
    monitor = asyncio.create_task(_monitoring_loop())
    try:
        yield
    finally:
        monitor.cancel()


app = FastAPI(
    title="SentinelChain AI API",
    version="1.0.0",
    description="Security-first inventory intelligence with a synthetic-data demo.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

request_windows: dict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    now = time.monotonic()
    key = request.client.host if request.client else "unknown"
    window = request_windows[key]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= settings.rate_limit_per_minute:
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"}, headers={"Retry-After": "60"})
    window.append(now)
    return await call_next(request)


def user_json(user: User) -> dict:
    return {"id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role}


def alert_json(alert: Alert) -> dict:
    return {
        "id": alert.id,
        "category": alert.category,
        "severity": alert.severity,
        "title": alert.title,
        "detail": alert.detail,
        "status": alert.status,
        "created_at": alert.created_at,
    }


def recommendation_json(item: Recommendation, product: Product | None = None) -> dict:
    return {
        "id": item.id,
        "sku": product.sku if product else None,
        "product_name": product.name if product else None,
        "reorder_point": item.reorder_point,
        "safety_stock": item.safety_stock,
        "eoq": item.eoq,
        "recommended_quantity": item.recommended_quantity,
        "supplier_risk": item.supplier_risk,
        "status": item.status,
        "decision_note": item.decision_note,
        "created_at": item.created_at,
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "sentinelchain-api"}


@app.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    append_audit(db, "auth.login", user.id, {"email": user.email})
    db.commit()
    return TokenResponse(access_token=create_access_token(user), user=user_json(user))


@app.get("/auth/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return user_json(user)


@app.get("/auth/permissions")
def auth_permissions(user: User = Depends(get_current_user)) -> dict:
    return {"role": user.role, "permissions": permissions_for(user.role)}


@app.get("/security/clearance-matrix")
def security_clearance_matrix(user: User = Depends(require_roles(Role.ADMIN))) -> dict:
    return clearance_matrix()


def _loads(value: str, fallback):
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def organization_json(profile: OrganizationProfile | None) -> dict:
    if profile is None:
        return {"configured": False, "name": "", "industry": "", "description": "", "objectives": [], "constraints": []}
    return {
        "configured": True,
        "id": profile.id,
        "name": profile.name,
        "industry": profile.industry,
        "description": profile.description,
        "objectives": _loads(profile.objectives_json, []),
        "constraints": _loads(profile.constraints_json, []),
        "status": profile.status,
        "updated_at": profile.updated_at,
    }


def evidence_json(item: EvidenceRecord) -> dict:
    return {
        "id": item.id,
        "node_id": item.node_id,
        "source_type": item.source_type,
        "external_id": item.external_id,
        "event_type": item.event_type,
        "summary": item.summary,
        "payload": _loads(item.payload_json, {}),
        "integrity_digest": item.integrity_digest,
        "confidence": item.confidence,
        "status": item.status,
        "conflict_key": item.conflict_key,
        "actor_id": item.actor_id,
        "occurred_at": item.occurred_at,
        "received_at": item.received_at,
    }


def action_json(item: ActionProposal, node: SupplyChainNode | None = None) -> dict:
    return {
        "id": item.id,
        "node_id": item.node_id,
        "node_name": node.name if node else None,
        "title": item.title,
        "reason": item.reason,
        "owner_role": item.owner_role,
        "urgency": item.urgency,
        "expected_impact": item.expected_impact,
        "due_at": item.due_at,
        "status": item.status,
        "decision_note": item.decision_note,
        "created_at": item.created_at,
    }


def _node_dict(node: SupplyChainNode) -> dict:
    return {
        "id": node.id,
        "chain_id": node.chain_id,
        "key": node.key,
        "name": node.name,
        "stage_type": node.stage_type,
        "owner_role": node.owner_role,
        "position": {"x": node.position_x, "y": node.position_y},
        "status": node.status,
        "metadata": _loads(node.metadata_json, {}),
        "active": node.active,
        "verified_at": node.verified_at,
        "verified_by": node.verified_by,
        "updated_at": node.updated_at,
    }


def _edge_dict(edge: SupplyChainEdge) -> dict:
    return {"id": edge.id, "source": edge.source_node_id, "target": edge.target_node_id, "label": edge.label, "status": edge.status}


def _chain_or_404(db: Session, chain_id: int) -> SupplyChain:
    chain = db.get(SupplyChain, chain_id)
    if chain is None:
        raise HTTPException(status_code=404, detail="Supply chain not found")
    return chain


def _node_or_404(db: Session, node_id: int, require_active: bool = True) -> SupplyChainNode:
    node = db.get(SupplyChainNode, node_id)
    if node is None or (require_active and not node.active):
        raise HTTPException(status_code=404, detail="Supply-chain node not found")
    return node


def _chain_summary(db: Session, chain: SupplyChain) -> dict:
    nodes = db.scalars(select(SupplyChainNode).where(SupplyChainNode.chain_id == chain.id)).all()
    pending_by_node = dict(db.execute(select(ActionProposal.node_id, func.count(ActionProposal.id)).where(ActionProposal.status == "pending").group_by(ActionProposal.node_id)).all())
    status_counts: dict[str, int] = {}
    for node in nodes:
        if node.active:
            status_counts[node.status] = status_counts.get(node.status, 0) + 1
    severity_order = ["critical", "disputed", "at_risk", "healthy"]
    worst = next((status for status in severity_order if status_counts.get(status)), "empty")
    return {
        "id": chain.id,
        "key": chain.key,
        "name": chain.name,
        "description": chain.description,
        "status": chain.status,
        "created_at": chain.created_at,
        "updated_at": chain.updated_at,
        "node_count": sum(1 for node in nodes if node.active),
        "archived_node_count": sum(1 for node in nodes if not node.active),
        "status_counts": status_counts,
        "worst_status": worst,
        "pending_actions": sum(pending_by_node.get(node.id, 0) for node in nodes if node.active),
        "updated_node_at": max((node.updated_at for node in nodes), default=chain.updated_at),
    }


def _chain_graph(db: Session, chain: SupplyChain) -> dict:
    nodes = db.scalars(
        select(SupplyChainNode).where(SupplyChainNode.chain_id == chain.id, SupplyChainNode.active.is_(True)).order_by(SupplyChainNode.position_x)
    ).all()
    active_ids = {node.id for node in nodes}
    edges = db.scalars(select(SupplyChainEdge).order_by(SupplyChainEdge.id)).all()
    edges = [edge for edge in edges if edge.source_node_id in active_ids and edge.target_node_id in active_ids]
    pending_by_node = dict(db.execute(select(ActionProposal.node_id, func.count(ActionProposal.id)).where(ActionProposal.status == "pending").group_by(ActionProposal.node_id)).all())
    return {
        "chain": _chain_summary(db, chain),
        "organization": organization_json(db.scalar(select(OrganizationProfile).limit(1))),
        "nodes": [{**_node_dict(node), "pending_actions": pending_by_node.get(node.id, 0)} for node in nodes],
        "edges": [_edge_dict(edge) for edge in edges],
        "updated_at": max((node.updated_at for node in nodes), default=datetime.now(timezone.utc)),
    }


def _run_node_guidance(db: Session, node: SupplyChainNode, actor_id: int | None, force: bool = False) -> tuple[GuidanceRun, list[ActionProposal]]:
    evidence_rows = db.scalars(select(EvidenceRecord).where(EvidenceRecord.node_id == node.id).order_by(EvidenceRecord.occurred_at.desc()).limit(20)).all()
    evidence = [evidence_json(item) for item in evidence_rows]
    node_data = _node_dict(node)
    profile = organization_json(db.scalar(select(OrganizationProfile).limit(1)))
    digest = context_digest(node_data, evidence)
    cached = db.scalar(select(GuidanceRun).where(GuidanceRun.node_id == node.id, GuidanceRun.context_digest == digest).order_by(GuidanceRun.created_at.desc()).limit(1))
    if cached and not force:
        actions = db.scalars(select(ActionProposal).where(ActionProposal.guidance_run_id == cached.id).order_by(ActionProposal.created_at.desc())).all()
        return cached, list(actions)
    if cached:
        cached.stale = True
    provider, payload = guidance_for(node_data, evidence, profile)
    run = GuidanceRun(
        node_id=node.id,
        context_digest=digest,
        provider=provider,
        status_summary=payload.status_summary,
        rationale=payload.rationale,
        evidence_ids_json=json.dumps(payload.evidence_ids),
        confidence=payload.confidence,
        no_action_required=payload.no_action_required,
        next_check_at=utc_after(payload.next_check_hours),
    )
    db.add(run)
    db.flush()
    actions: list[ActionProposal] = []
    for suggestion in payload.actions:
        existing = db.scalar(select(ActionProposal).where(ActionProposal.node_id == node.id, ActionProposal.title == suggestion.title, ActionProposal.status == "pending"))
        if existing:
            actions.append(existing)
            continue
        action = ActionProposal(
            node_id=node.id,
            guidance_run_id=run.id,
            title=suggestion.title,
            reason=suggestion.reason,
            owner_role=suggestion.owner_role,
            urgency=suggestion.urgency,
            expected_impact=suggestion.expected_impact,
            due_at=utc_after(suggestion.due_hours),
        )
        db.add(action)
        actions.append(action)
    append_audit(db, "guidance.generated", actor_id, {"node_id": node.id, "provider": provider, "evidence_ids": payload.evidence_ids, "action_count": len(actions)})
    db.commit()
    return run, actions


def guidance_json(run: GuidanceRun, actions: list[ActionProposal]) -> dict:
    return {
        "id": run.id,
        "provider": run.provider,
        "status_summary": run.status_summary,
        "rationale": run.rationale,
        "evidence_ids": _loads(run.evidence_ids_json, []),
        "confidence": run.confidence,
        "no_action_required": run.no_action_required,
        "next_check_at": run.next_check_at,
        "stale": run.stale,
        "actions": [action_json(item) for item in actions],
        "created_at": run.created_at,
    }


@app.get("/organization/context")
def get_organization_context(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return organization_json(db.scalar(select(OrganizationProfile).limit(1)))


@app.put("/organization/context")
def put_organization_context(
    body: OrganizationContextRequest,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    profile = db.scalar(select(OrganizationProfile).limit(1))
    if profile is None:
        profile = OrganizationProfile(name=body.name)
        db.add(profile)
    profile.name = body.name
    profile.industry = body.industry
    profile.description = body.description
    profile.objectives_json = json.dumps(body.objectives)
    profile.constraints_json = json.dumps(body.constraints)
    profile.updated_by = user.id
    append_audit(db, "organization.context_updated", user.id, {"name": body.name, "industry": body.industry})
    db.commit()
    db.refresh(profile)
    return organization_json(profile)


@app.get("/users/me/context")
def get_user_context(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    context = db.scalar(select(UserContext).where(UserContext.user_id == user.id))
    if context is None:
        return {"configured": False, "owned_stages": [], "decision_limits": {}, "escalation_preferences": {}, "timezone_name": "Asia/Calcutta"}
    return {
        "configured": True,
        "owned_stages": _loads(context.owned_stages_json, []),
        "decision_limits": _loads(context.decision_limits_json, {}),
        "escalation_preferences": _loads(context.escalation_preferences_json, {}),
        "timezone_name": context.timezone_name,
    }


@app.put("/users/me/context")
def put_user_context(body: UserContextRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    context = db.scalar(select(UserContext).where(UserContext.user_id == user.id))
    if context is None:
        context = UserContext(user_id=user.id)
        db.add(context)
    context.owned_stages_json = json.dumps(body.owned_stages)
    context.decision_limits_json = json.dumps(body.decision_limits)
    context.escalation_preferences_json = json.dumps(body.escalation_preferences)
    context.timezone_name = body.timezone_name
    append_audit(db, "user.context_updated", user.id, {"owned_stages": body.owned_stages})
    db.commit()
    return get_user_context(user, db)


@app.get("/supply-chains")
def list_supply_chains(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    chains = db.scalars(select(SupplyChain).order_by(SupplyChain.status, SupplyChain.id)).all()
    return {
        "chains": [_chain_summary(db, chain) for chain in chains],
        "default_chain_id": next((chain.id for chain in chains if chain.status == "active"), None),
    }


@app.post("/supply-chains", status_code=201)
def create_supply_chain(
    body: SupplyChainCreateRequest,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    if db.scalar(select(SupplyChain).where(SupplyChain.key == body.key)):
        raise HTTPException(status_code=409, detail="A supply chain with this key already exists")
    chain = SupplyChain(key=body.key, name=body.name, description=body.description, created_by=user.id)
    db.add(chain)
    db.flush()
    append_audit(db, "supply_chain.chain_created", user.id, {"chain_id": chain.id, "key": chain.key, "name": chain.name})
    db.commit()
    return _chain_summary(db, chain)


@app.get("/supply-chains/{chain_id}")
def get_supply_chain_graph(chain_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return _chain_graph(db, _chain_or_404(db, chain_id))


@app.put("/supply-chains/{chain_id}")
def update_supply_chain(
    chain_id: int,
    body: SupplyChainUpdateRequest,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    chain = _chain_or_404(db, chain_id)
    changes: dict[str, object] = {}
    if body.key is not None and body.key != chain.key:
        if db.scalar(select(SupplyChain).where(SupplyChain.key == body.key, SupplyChain.id != chain.id)):
            raise HTTPException(status_code=409, detail="A supply chain with this key already exists")
        changes["key"] = {"from": chain.key, "to": body.key}
        chain.key = body.key
    if body.name is not None and body.name != chain.name:
        changes["name"] = body.name
        chain.name = body.name
    if body.description is not None and body.description != chain.description:
        changes["description"] = body.description
        chain.description = body.description
    if changes:
        append_audit(db, "supply_chain.chain_updated", user.id, {"chain_id": chain.id, "changes": changes})
        db.commit()
    return _chain_summary(db, chain)


@app.post("/supply-chains/{chain_id}/archive")
def archive_supply_chain(chain_id: int, user: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)) -> dict:
    chain = _chain_or_404(db, chain_id)
    if chain.status == "archived":
        raise HTTPException(status_code=409, detail="Supply chain is already archived")
    chain.status = "archived"
    append_audit(db, "supply_chain.chain_archived", user.id, {"chain_id": chain.id, "key": chain.key})
    db.commit()
    return _chain_summary(db, chain)


@app.post("/supply-chains/{chain_id}/restore")
def restore_supply_chain(chain_id: int, user: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)) -> dict:
    chain = _chain_or_404(db, chain_id)
    if chain.status != "archived":
        raise HTTPException(status_code=409, detail="Supply chain is not archived")
    chain.status = "active"
    append_audit(db, "supply_chain.chain_restored", user.id, {"chain_id": chain.id, "key": chain.key})
    db.commit()
    return _chain_summary(db, chain)


def _require_editable_chain(db: Session, chain_id: int) -> SupplyChain:
    chain = _chain_or_404(db, chain_id)
    if chain.status != "active":
        raise HTTPException(status_code=409, detail="Restore this supply chain before editing it")
    return chain


@app.post("/supply-chains/{chain_id}/nodes", status_code=201)
def create_node(
    chain_id: int,
    body: NodeCreateRequest,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    chain = _require_editable_chain(db, chain_id)
    if db.scalar(select(SupplyChainNode).where(SupplyChainNode.chain_id == chain.id, SupplyChainNode.key == body.key)):
        raise HTTPException(status_code=409, detail="A node with this key already exists in the chain")
    existing_count = db.scalar(select(func.count(SupplyChainNode.id)).where(SupplyChainNode.chain_id == chain.id)) or 0
    node = SupplyChainNode(
        chain_id=chain.id,
        key=body.key,
        name=body.name,
        stage_type=body.stage_type,
        owner_role=body.owner_role,
        position_x=body.position_x if body.position_x is not None else float(existing_count * 260),
        position_y=body.position_y if body.position_y is not None else float(80 if existing_count % 2 else 140),
        metadata_json=json.dumps(body.metadata, sort_keys=True),
    )
    db.add(node)
    db.flush()
    append_audit(db, "supply_chain.node_created", user.id, {"node_id": node.id, "chain_id": chain.id, "key": node.key, "name": node.name})
    db.commit()
    return _node_dict(node)


@app.put("/nodes/{node_id}")
def update_node(
    node_id: int,
    body: NodeUpdateRequest,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    node = _node_or_404(db, node_id, require_active=False)
    _require_editable_chain(db, node.chain_id)
    changes: dict[str, object] = {}
    if body.key is not None and body.key != node.key:
        if db.scalar(select(SupplyChainNode).where(SupplyChainNode.chain_id == node.chain_id, SupplyChainNode.key == body.key, SupplyChainNode.id != node.id)):
            raise HTTPException(status_code=409, detail="A node with this key already exists in the chain")
        changes["key"] = {"from": node.key, "to": body.key}
        node.key = body.key
    for field in ("name", "stage_type", "owner_role"):
        value = getattr(body, field)
        if value is not None and value != getattr(node, field):
            changes[field] = value
            setattr(node, field, value)
    if body.position_x is not None and body.position_x != node.position_x:
        changes["position_x"] = body.position_x
        node.position_x = body.position_x
    if body.position_y is not None and body.position_y != node.position_y:
        changes["position_y"] = body.position_y
        node.position_y = body.position_y
    if body.metadata is not None:
        canonical = json.dumps(body.metadata, sort_keys=True)
        if canonical != node.metadata_json:
            changes["metadata"] = body.metadata
            node.metadata_json = canonical
    if changes:
        append_audit(db, "supply_chain.node_updated", user.id, {"node_id": node.id, "changes": changes})
        db.commit()
    return _node_dict(node)


@app.delete("/nodes/{node_id}")
def deactivate_node(node_id: int, user: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)) -> dict:
    node = _node_or_404(db, node_id, require_active=False)
    if not node.active:
        raise HTTPException(status_code=409, detail="Node is already deactivated")
    node.active = False
    append_audit(db, "supply_chain.node_deactivated", user.id, {"node_id": node.id, "chain_id": node.chain_id, "key": node.key})
    db.commit()
    return _node_dict(node)


@app.post("/nodes/{node_id}/activate")
def activate_node(node_id: int, user: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)) -> dict:
    node = _node_or_404(db, node_id, require_active=False)
    if node.active:
        raise HTTPException(status_code=409, detail="Node is already active")
    node.active = True
    append_audit(db, "supply_chain.node_activated", user.id, {"node_id": node.id, "chain_id": node.chain_id, "key": node.key})
    db.commit()
    return _node_dict(node)


@app.post("/supply-chains/{chain_id}/edges", status_code=201)
def create_edge(
    chain_id: int,
    body: EdgeCreateRequest,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    chain = _require_editable_chain(db, chain_id)
    if body.source_node_id == body.target_node_id:
        raise HTTPException(status_code=422, detail="An edge cannot connect a node to itself")
    source = _node_or_404(db, body.source_node_id, require_active=False)
    target = _node_or_404(db, body.target_node_id, require_active=False)
    if source.chain_id != chain.id or target.chain_id != chain.id:
        raise HTTPException(status_code=422, detail="Both endpoints must belong to this supply chain")
    existing = db.scalar(
        select(SupplyChainEdge).where(
            SupplyChainEdge.source_node_id == source.id,
            SupplyChainEdge.target_node_id == target.id,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="These nodes are already connected")
    edge = SupplyChainEdge(source_node_id=source.id, target_node_id=target.id, label=body.label)
    db.add(edge)
    db.flush()
    append_audit(db, "supply_chain.edge_created", user.id, {"edge_id": edge.id, "chain_id": chain.id, "source": source.id, "target": target.id})
    db.commit()
    return _edge_dict(edge)


@app.put("/edges/{edge_id}")
def update_edge(
    edge_id: int,
    body: EdgeUpdateRequest,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    edge = db.get(SupplyChainEdge, edge_id)
    if edge is None:
        raise HTTPException(status_code=404, detail="Edge not found")
    changes: dict = {"edge_id": edge.id}
    new_source = edge.source_node_id if body.source_node_id is None else body.source_node_id
    new_target = edge.target_node_id if body.target_node_id is None else body.target_node_id
    if new_source != edge.source_node_id or new_target != edge.target_node_id:
        if new_source == new_target:
            raise HTTPException(status_code=422, detail="An edge cannot connect a node to itself")
        original = _node_or_404(db, edge.source_node_id, require_active=False)
        source = _node_or_404(db, new_source, require_active=False)
        target = _node_or_404(db, new_target, require_active=False)
        if source.chain_id != original.chain_id or target.chain_id != original.chain_id:
            raise HTTPException(status_code=422, detail="Both endpoints must belong to this supply chain")
        existing = db.scalar(
            select(SupplyChainEdge).where(
                SupplyChainEdge.source_node_id == source.id,
                SupplyChainEdge.target_node_id == target.id,
                SupplyChainEdge.id != edge.id,
            )
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="These nodes are already connected")
        edge.source_node_id = source.id
        edge.target_node_id = target.id
        changes.update({"source": source.id, "target": target.id})
    if body.label is not None and body.label != edge.label:
        edge.label = body.label
        changes["label"] = body.label
    if len(changes) > 1:
        append_audit(db, "supply_chain.edge_updated", user.id, changes)
        db.commit()
    return _edge_dict(edge)


@app.delete("/edges/{edge_id}")
def delete_edge(edge_id: int, user: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)) -> dict:
    edge = db.get(SupplyChainEdge, edge_id)
    if edge is None:
        raise HTTPException(status_code=404, detail="Edge not found")
    payload = {"edge_id": edge.id, "source": edge.source_node_id, "target": edge.target_node_id}
    db.delete(edge)
    append_audit(db, "supply_chain.edge_deleted", user.id, payload)
    db.commit()
    return {"status": "deleted", **payload}


@app.get("/supply-chain")
def supply_chain(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    chain = db.scalar(select(SupplyChain).where(SupplyChain.status == "active").order_by(SupplyChain.id))
    if chain is None:
        return {"chain": None, "organization": organization_json(db.scalar(select(OrganizationProfile).limit(1))), "nodes": [], "edges": [], "updated_at": datetime.now(timezone.utc)}
    return _chain_graph(db, chain)


def _resolve_evidence_node(body: EvidenceRequest, db: Session) -> SupplyChainNode:
    if body.node_id is not None:
        node = db.get(SupplyChainNode, body.node_id)
        if node is None or not node.active:
            raise HTTPException(status_code=404, detail="Supply-chain node not found")
        return node
    if not body.node_key:
        raise HTTPException(status_code=422, detail="Provide node_id or node_key")
    statement = select(SupplyChainNode).where(SupplyChainNode.key == body.node_key, SupplyChainNode.active.is_(True))
    if body.chain_id is not None:
        statement = statement.where(SupplyChainNode.chain_id == body.chain_id)
    matches = db.scalars(statement).all()
    if not matches:
        raise HTTPException(status_code=404, detail="Supply-chain node not found")
    if len(matches) > 1:
        raise HTTPException(status_code=422, detail="node_key is ambiguous across supply chains; send chain_id or node_id")
    return matches[0]


def _store_evidence(body: EvidenceRequest, source_type: str, user: User, db: Session, node: SupplyChainNode) -> EvidenceRecord:
    if body.external_id:
        existing = db.scalar(select(EvidenceRecord).where(EvidenceRecord.external_id == body.external_id))
        if existing:
            return existing
    canonical = json.dumps(body.payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"{body.event_type}:{body.summary}:{canonical}".encode()).hexdigest()
    item = EvidenceRecord(
        node_id=node.id,
        source_type=source_type,
        external_id=body.external_id,
        event_type=body.event_type,
        summary=body.summary,
        payload_json=canonical,
        integrity_digest=digest,
        confidence=body.confidence,
        conflict_key=body.conflict_key,
        actor_id=user.id,
        occurred_at=(body.occurred_at or datetime.now(timezone.utc)).replace(tzinfo=None),
    )
    if body.conflict_key:
        candidates = db.scalars(select(EvidenceRecord).where(EvidenceRecord.node_id == node.id, EvidenceRecord.conflict_key == body.conflict_key, EvidenceRecord.status == "accepted")).all()
        if any(candidate.integrity_digest != digest for candidate in candidates):
            item.status = "disputed"
            node.status = "disputed"
            for candidate in candidates:
                candidate.status = "disputed"
    if item.status == "accepted" and body.event_type.endswith(("delay", "exception", "blocked")):
        node.status = "at_risk"
    # New evidence voids any prior auditor sign-off: the node must be re-verified.
    node.verified_at = None
    node.verified_by = None
    db.add(item)
    db.flush()
    append_audit(db, "evidence.received", user.id, {"evidence_id": item.id, "node_id": node.id, "source_type": source_type, "status": item.status, "digest": digest})
    db.commit()
    _run_node_guidance(db, node, user.id)
    return item


@app.post("/events")
def ingest_event(body: EvidenceRequest, user: User = Depends(require_roles(Role.ADMIN, Role.ANALYST)), db: Session = Depends(get_db)) -> dict:
    node = _resolve_evidence_node(body, db)
    return evidence_json(_store_evidence(body, "api", user, db, node))


@app.post("/nodes/{node_id}/manual-events")
def add_manual_event(node_id: int, body: EvidenceRequest, user: User = Depends(require_roles(Role.ADMIN, Role.ANALYST, Role.MANAGER)), db: Session = Depends(get_db)) -> dict:
    node = _node_or_404(db, node_id)
    return evidence_json(_store_evidence(body, "manual", user, db, node))


@app.get("/nodes/{node_id}/inspector")
def node_inspector(node_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    node = db.get(SupplyChainNode, node_id)
    if node is None or not node.active:
        raise HTTPException(status_code=404, detail="Supply-chain node not found")
    evidence = db.scalars(select(EvidenceRecord).where(EvidenceRecord.node_id == node.id).order_by(EvidenceRecord.occurred_at.desc()).limit(50)).all()
    run, actions = _run_node_guidance(db, node, user.id)
    users = db.scalars(select(User).order_by(User.id)).all()
    return {
        "node": _node_dict(node),
        "step": step_spec(node, list(users)),
        "evidence": [evidence_json(item) for item in evidence],
        "guidance": guidance_json(run, actions),
    }


@app.post("/nodes/{node_id}/guidance/refresh")
def refresh_guidance(node_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    node = _node_or_404(db, node_id)
    previous = db.scalars(select(GuidanceRun).where(GuidanceRun.node_id == node.id, GuidanceRun.stale.is_(False))).all()
    for item in previous:
        item.stale = True
    db.commit()
    run, actions = _run_node_guidance(db, node, user.id, force=True)
    return guidance_json(run, actions)


@app.post("/nodes/{node_id}/verify")
def verify_node(
    node_id: int,
    body: VerifyNodeRequest,
    user: User = Depends(require_roles(Role.AUDITOR, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    node = _node_or_404(db, node_id)
    node.verified_at = utcnow()
    node.verified_by = user.id
    append_audit(db, "node.verified", user.id, {"node_id": node.id, "chain_id": node.chain_id, "key": node.key, "note": body.note})
    db.commit()
    return _node_dict(node)


@app.get("/actions")
def action_queue(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    statement = select(ActionProposal).order_by(ActionProposal.status, ActionProposal.due_at, ActionProposal.created_at.desc())
    if user.role == Role.ANALYST.value:
        statement = statement.where(ActionProposal.owner_role == user.role)
    items = db.scalars(statement).all()
    nodes = {node.id: node for node in db.scalars(select(SupplyChainNode)).all()}
    return [action_json(item, nodes.get(item.node_id)) for item in items]


@app.post("/actions/{action_id}/decision")
def decide_action(action_id: int, body: ActionDecisionRequest, user: User = Depends(require_roles(Role.ADMIN, Role.MANAGER)), db: Session = Depends(get_db)) -> dict:
    result = db.execute(update(ActionProposal).where(ActionProposal.id == action_id, ActionProposal.status == body.expected_status).values(status=body.decision, decided_by=user.id, decision_note=body.note))
    if result.rowcount == 0:
        existing = db.get(ActionProposal, action_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Action proposal not found")
        raise HTTPException(status_code=409, detail=f"Action proposal is already {existing.status}")
    item = db.get(ActionProposal, action_id)
    append_audit(db, f"action.{body.decision}", user.id, {"action_id": action_id, "note": body.note})
    db.commit()
    return action_json(item)


@app.post("/actions/{action_id}/escalate")
def escalate_action(
    action_id: int,
    body: EscalateActionRequest,
    user: User = Depends(require_roles(Role.ADMIN, Role.MANAGER)),
    db: Session = Depends(get_db),
) -> dict:
    item = db.get(ActionProposal, action_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Action proposal not found")
    if item.status != "pending":
        raise HTTPException(status_code=409, detail=f"Action proposal is already {item.status}")
    item.urgency = "critical"
    append_audit(db, "action.escalated", user.id, {"action_id": action_id, "note": body.note})
    db.commit()
    return action_json(item)


@app.get("/dashboard")
def dashboard(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    products = db.scalars(select(Product).order_by(Product.sku)).all()
    alerts = db.scalars(select(Alert).where(Alert.status == "open").order_by(Alert.created_at.desc()).limit(5)).all()
    recommendations = db.scalars(select(Recommendation).order_by(Recommendation.created_at.desc()).limit(5)).all()
    recent_start = date.today() - timedelta(days=29)
    sales = db.execute(
        select(SaleRecord.sold_at, func.sum(SaleRecord.quantity))
        .where(SaleRecord.sold_at >= recent_start)
        .group_by(SaleRecord.sold_at)
        .order_by(SaleRecord.sold_at)
    ).all()
    product_map = {product.id: product for product in products}
    low_stock = sum(1 for product in products if product.current_stock < product.lead_time_days * 10)
    return {
        "synthetic": True,
        "kpis": {
            "total_skus": len(products),
            "low_stock_skus": low_stock,
            "open_security_alerts": sum(1 for alert in alerts if alert.category in {"integrity", "authentication", "authorization"}),
            "pending_approvals": sum(1 for item in recommendations if item.status == "pending"),
        },
        "demand_series": [{"date": sold_at.isoformat(), "quantity": round(float(quantity), 1)} for sold_at, quantity in sales],
        "products": [
            {
                "sku": product.sku,
                "name": product.name,
                "current_stock": product.current_stock,
                "lead_time_days": product.lead_time_days,
                "health": "critical" if product.current_stock < product.lead_time_days * 5 else "watch" if product.current_stock < product.lead_time_days * 10 else "healthy",
            }
            for product in products
        ],
        "alerts": [alert_json(alert) for alert in alerts],
        "recommendations": [recommendation_json(item, product_map.get(item.product_id)) for item in recommendations],
    }


def _prepare_import(body: ImportRequest) -> tuple[bytes, object]:
    content = body.csv_content.encode()
    if not verify_import_signature(content, body.signature):
        raise HTTPException(status_code=400, detail="Manifest signature does not match the dataset")
    try:
        return content, analyze_sales(parse_sales_csv(body.csv_content))
    except DatasetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/imports/preview")
def preview_import(
    body: ImportRequest,
    _: User = Depends(require_roles(Role.ADMIN, Role.ANALYST)),
) -> dict:
    content, analysis = _prepare_import(body)
    return {
        "dataset_name": body.dataset_name,
        "digest": hashlib.sha256(content).hexdigest(),
        "row_count": len(analysis.frame),
        "accepted_count": len(analysis.accepted_indices),
        "quarantined": analysis.quarantined,
        "signature_valid": True,
    }


@app.post("/imports")
def ingest_import(
    body: ImportRequest,
    user: User = Depends(require_roles(Role.ADMIN, Role.ANALYST)),
    db: Session = Depends(get_db),
) -> dict:
    content, analysis = _prepare_import(body)
    digest = hashlib.sha256(content).hexdigest()
    if db.scalar(select(ImportBatch).where(ImportBatch.digest == digest)):
        raise HTTPException(status_code=409, detail="This exact dataset has already been imported")
    batch = ImportBatch(
        dataset_name=body.dataset_name,
        digest=digest,
        status="quarantined" if analysis.quarantined else "accepted",
        row_count=len(analysis.frame),
        quarantined_count=len(analysis.quarantined),
        created_by=user.id,
    )
    db.add(batch)
    db.flush()
    product_map = {item.sku: item for item in db.scalars(select(Product)).all()}
    accepted = 0
    quarantined = list(analysis.quarantined)
    quarantined_indexes = {item["row_number"] - 2 for item in quarantined}
    for index in analysis.accepted_indices:
        row = analysis.frame.loc[index]
        product = product_map.get(str(row["sku"]))
        if product is None:
            quarantined_indexes.add(index)
            quarantined.append(
                {
                    "row_number": index + 2,
                    "record": {"sku": str(row["sku"]), "date": row["date"].date().isoformat(), "quantity": float(row["quantity"])},
                    "reason": "unknown SKU",
                }
            )
            continue
        db.add(SaleRecord(product_id=product.id, sold_at=row["date"].date(), quantity=float(row["quantity"]), source_import_id=batch.id))
        accepted += 1
    for item in quarantined:
        db.add(
            QuarantinedRecord(
                import_batch_id=batch.id,
                row_number=item["row_number"],
                payload_json=json.dumps(item["record"], sort_keys=True),
                reason=item["reason"],
            )
        )
    batch.quarantined_count = len(quarantined)
    batch.status = "quarantined" if quarantined else "accepted"
    if quarantined:
        db.add(
            Alert(
                category="integrity",
                severity="high",
                title=f"{len(quarantined)} import record(s) quarantined",
                detail=f"{body.dataset_name} contained records that failed anomaly or business-rule checks.",
            )
        )
    append_audit(db, "import.ingested", user.id, {"batch_id": batch.id, "digest": digest, "accepted": accepted, "quarantined": len(quarantined)})
    db.commit()
    return {"id": batch.id, "status": batch.status, "accepted_count": accepted, "quarantined": quarantined, "digest": digest}


@app.post("/forecasts/{sku}/train")
def create_forecast(
    sku: str,
    user: User = Depends(require_roles(Role.ADMIN, Role.ANALYST)),
    db: Session = Depends(get_db),
) -> dict:
    product = db.scalar(select(Product).where(Product.sku == sku))
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    records = db.scalars(select(SaleRecord).where(SaleRecord.product_id == product.id).order_by(SaleRecord.sold_at)).all()
    try:
        result = train_forecast(pd.DataFrame([{"date": row.sold_at, "quantity": row.quantity} for row in records]))
    except DatasetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    forecast = Forecast(
        product_id=product.id,
        horizon_days=14,
        daily_demand=result["daily_demand"],
        mae=result["mae"],
        rmse=result["rmse"],
        mape=result["mape"],
        baseline_mae=result["baseline_mae"],
        model_name=result["model_name"],
        explanation_json=json.dumps(result["explanation"]),
    )
    db.add(forecast)
    db.flush()
    append_audit(db, "forecast.trained", user.id, {"forecast_id": forecast.id, "sku": sku, "model": forecast.model_name})
    db.commit()
    return {"id": forecast.id, "sku": sku, **result, "horizon_days": 14, "synthetic": True}


@app.get("/forecasts/{sku}")
def latest_forecast(sku: str, _: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    product = db.scalar(select(Product).where(Product.sku == sku))
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    forecast = db.scalar(select(Forecast).where(Forecast.product_id == product.id).order_by(Forecast.created_at.desc()).limit(1))
    if forecast is None:
        raise HTTPException(status_code=404, detail="No forecast has been trained for this product")
    return {
        "id": forecast.id,
        "sku": sku,
        "daily_demand": forecast.daily_demand,
        "mae": forecast.mae,
        "rmse": forecast.rmse,
        "mape": forecast.mape,
        "baseline_mae": forecast.baseline_mae,
        "model_name": forecast.model_name,
        "explanation": json.loads(forecast.explanation_json),
        "created_at": forecast.created_at,
    }


@app.post("/recommendations/generate/{sku}")
def generate_recommendation(
    sku: str,
    user: User = Depends(require_roles(Role.ADMIN, Role.ANALYST)),
    db: Session = Depends(get_db),
) -> dict:
    product = db.scalar(select(Product).where(Product.sku == sku))
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    forecast = db.scalar(select(Forecast).where(Forecast.product_id == product.id).order_by(Forecast.created_at.desc()).limit(1))
    if forecast is None:
        raise HTTPException(status_code=409, detail="Train a forecast before generating a recommendation")
    quantities = [float(value) for value in db.scalars(select(SaleRecord.quantity).where(SaleRecord.product_id == product.id)).all()]
    annual_demand = sum(quantities[-90:]) / min(len(quantities), 90) * 365
    policy = inventory_policy(
        forecast.daily_demand,
        float(pd.Series(quantities[-30:]).std() or 0),
        product.lead_time_days,
        annual_demand,
        product.order_cost,
        product.unit_cost,
        product.holding_cost_rate,
        product.current_stock,
    )
    suppliers = db.scalars(select(Supplier)).all()
    risk = min((supplier_risk(s.reliability, s.average_lead_time, s.defect_rate, s.price_variance) for s in suppliers), default=100.0)
    item = Recommendation(product_id=product.id, forecast_id=forecast.id, supplier_risk=risk, **policy)
    db.add(item)
    db.flush()
    append_audit(db, "recommendation.generated", user.id, {"recommendation_id": item.id, "sku": sku, **policy, "supplier_risk": risk})
    db.commit()
    return recommendation_json(item, product)


@app.get("/recommendations")
def recommendations(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    items = db.scalars(select(Recommendation).order_by(Recommendation.created_at.desc())).all()
    products = {item.id: item for item in db.scalars(select(Product)).all()}
    return [recommendation_json(item, products.get(item.product_id)) for item in items]


@app.post("/recommendations/{recommendation_id}/decision")
def decide_recommendation(
    recommendation_id: int,
    body: DecisionRequest,
    user: User = Depends(require_roles(Role.ADMIN, Role.MANAGER)),
    db: Session = Depends(get_db),
) -> dict:
    result = db.execute(
        update(Recommendation)
        .where(Recommendation.id == recommendation_id, Recommendation.status == body.expected_status)
        .values(status=body.decision, decided_by=user.id, decision_note=body.note)
    )
    if result.rowcount == 0:
        existing = db.get(Recommendation, recommendation_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        raise HTTPException(status_code=409, detail=f"Recommendation is already {existing.status}")
    item = db.get(Recommendation, recommendation_id)
    append_audit(db, f"recommendation.{body.decision}", user.id, {"recommendation_id": recommendation_id, "note": body.note})
    db.commit()
    return recommendation_json(item)


@app.get("/suppliers")
def suppliers(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Supplier).order_by(Supplier.name)).all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "reliability": row.reliability,
            "average_lead_time": row.average_lead_time,
            "defect_rate": row.defect_rate,
            "price_variance": row.price_variance,
            "risk_score": supplier_risk(row.reliability, row.average_lead_time, row.defect_rate, row.price_variance),
        }
        for row in rows
    ]


@app.get("/alerts")
def alerts(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [alert_json(item) for item in db.scalars(select(Alert).order_by(Alert.created_at.desc())).all()]


@app.get("/audit")
def audit_history(
    _: User = Depends(require_roles(Role.ADMIN, Role.AUDITOR)),
    db: Session = Depends(get_db),
) -> dict:
    valid, broken_at = verify_chain(db)
    events = db.scalars(select(AuditEvent).order_by(AuditEvent.sequence.desc()).limit(100)).all()
    return {
        "valid": valid,
        "broken_at": broken_at,
        "events": [
            {
                "sequence": event.sequence,
                "event_type": event.event_type,
                "actor_id": event.actor_id,
                "payload": json.loads(event.payload_json),
                "previous_hash": event.previous_hash,
                "event_hash": event.event_hash,
                "created_at": event.created_at,
            }
            for event in events
        ],
    }


@app.post("/demo/attacks")
def run_attack(
    body: AttackRequest,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail="Demo attack utility is disabled")
    product = db.scalar(select(Product).where(Product.sku == body.sku))
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    attack_details = {
        "demand_poisoning": ("integrity", "Injected demand spike quarantined", "quantity=12000", 12000),
        "inventory_manipulation": ("integrity", "Impossible inventory adjustment blocked", "stock=-500", 500),
        "supplier_spoofing": ("authentication", "Unverified supplier identity blocked", "supplier=Nova Components LLC", 800),
    }
    category, title, evidence, unsafe_quantity = attack_details[body.attack_type]
    alert = Alert(category=category, severity="critical", title=title, detail=f"Demo-only {body.attack_type.replace('_', ' ')} attempt for {body.sku}: {evidence}.")
    db.add(alert)
    # Demo attacks have no real import batch; preserve evidence in the audit and alert stores.
    append_audit(db, "demo.attack_blocked", user.id, {"attack_type": body.attack_type, "sku": body.sku, "evidence": evidence})
    db.commit()
    safe_quantity = max(0, round(product.lead_time_days * 24 - product.current_stock))
    return {
        "attack_type": body.attack_type,
        "detected": True,
        "quarantined": True,
        "alert_id": alert.id,
        "unsafe_decision": {"purchase_quantity": unsafe_quantity, "source": "compromised input"},
        "protected_decision": {"purchase_quantity": safe_quantity, "source": "last verified data"},
        "message": "Compromised input was blocked before forecasting or approval.",
    }


# Universal SCM operating layer -------------------------------------------------
def _record(db: Session, event: str, user: User, values: dict) -> dict:
    append_audit(db, event, user.id, values)
    db.commit()
    return values


def _dump(obj, extra: dict | None = None) -> dict:
    data = {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
    if extra:
        data.update(extra)
    return data


@app.get("/node-templates")
def list_node_templates(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [_dump(x, {"field_definitions": json.loads(x.field_definitions_json), "enabled_modules": json.loads(x.enabled_modules_json)}) for x in db.scalars(select(NodeTemplate).order_by(NodeTemplate.id)).all()]


@app.post("/node-templates")
def create_node_template(body: NodeTemplateRequest, user: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)):
    if db.scalar(select(NodeTemplate).where(NodeTemplate.key == body.key)):
        raise HTTPException(409, "Template key already exists")
    item = NodeTemplate(name=body.name, key=body.key, description=body.description,
                        field_definitions_json=json.dumps(body.field_definitions),
                        enabled_modules_json=json.dumps(body.enabled_modules), created_by=user.id)
    db.add(item); db.flush(); _record(db, "node_template.created", user, {"id": item.id}); return _dump(item, {"field_definitions": body.field_definitions, "enabled_modules": body.enabled_modules})


@app.put("/node-templates/{template_id}")
def update_node_template(template_id: int, body: NodeTemplateRequest, user: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)):
    item = db.get(NodeTemplate, template_id)
    if item is None: raise HTTPException(404, "Template not found")
    item.name, item.key, item.description = body.name, body.key, body.description
    item.field_definitions_json, item.enabled_modules_json = json.dumps(body.field_definitions), json.dumps(body.enabled_modules)
    db.flush(); _record(db, "node_template.updated", user, {"id": item.id}); return _dump(item)


@app.delete("/node-templates/{template_id}")
def delete_node_template(template_id: int, user: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)):
    item = db.get(NodeTemplate, template_id)
    if item is None: raise HTTPException(404, "Template not found")
    item.active = False; db.flush(); _record(db, "node_template.disabled", user, {"id": item.id}); return {"status": "disabled"}


@app.post("/workflows")
def create_workflow(body: WorkflowRequest, user: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)):
    item = Workflow(name=body.name, trigger_json=json.dumps(body.trigger), conditions_json=json.dumps(body.conditions), actions_json=json.dumps(body.actions), status=body.status, created_by=user.id)
    db.add(item); db.flush(); _record(db, "workflow.created", user, {"id": item.id}); return _dump(item)


@app.get("/workflows")
def list_workflows(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [_dump(x) for x in db.scalars(select(Workflow).order_by(Workflow.id)).all()]


@app.patch("/workflows/{workflow_id}")
def update_workflow(workflow_id: int, body: dict, user: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)):
    workflow = db.get(Workflow, workflow_id)
    if workflow is None: raise HTTPException(404, "Workflow not found")
    if "status" in body and body["status"] not in {"draft", "active", "disabled"}: raise HTTPException(422, "Invalid workflow state")
    for key, column in (("name", "name"), ("status", "status")):
        if key in body: setattr(workflow, column, body[key])
    for key, column in (("trigger", "trigger_json"), ("conditions", "conditions_json"), ("actions", "actions_json")):
        if key in body: setattr(workflow, column, json.dumps(body[key]))
    db.flush(); _record(db, "workflow.updated", user, {"id": workflow.id}); return _dump(workflow)


@app.post("/workflows/{workflow_id}/executions")
def execute_workflow(workflow_id: int, payload: dict = {}, user: User = Depends(require_roles(Role.ADMIN, Role.MANAGER)), db: Session = Depends(get_db)):
    workflow = db.get(Workflow, workflow_id)
    if workflow is None or workflow.status != "active": raise HTTPException(409, "Workflow is not active")
    execution = WorkflowExecution(workflow_id=workflow_id, status="completed", input_json=json.dumps(payload), output_json=json.dumps({"actions": json.loads(workflow.actions_json)}), started_at=utcnow(), finished_at=utcnow(), created_by=user.id)
    db.add(execution); db.flush(); _record(db, "workflow.executed", user, {"id": execution.id, "workflow_id": workflow_id}); return _dump(execution)


@app.post("/operational-tasks")
def create_task(body: TaskRequest, user: User = Depends(require_roles(Role.ADMIN, Role.MANAGER, Role.ANALYST)), db: Session = Depends(get_db)):
    item = OperationalTask(title=body.title, description=body.description, priority=body.priority, assigned_to=body.assigned_to, created_by=user.id)
    db.add(item); db.flush(); _record(db, "task.created", user, {"id": item.id}); return _dump(item)


@app.get("/operational-tasks")
def list_tasks(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [_dump(x) for x in db.scalars(select(OperationalTask).order_by(OperationalTask.id.desc())).all()]


@app.patch("/operational-tasks/{task_id}")
def update_task(task_id: int, body: dict, user: User = Depends(require_roles(Role.ADMIN, Role.MANAGER, Role.ANALYST)), db: Session = Depends(get_db)):
    task = db.get(OperationalTask, task_id)
    if task is None: raise HTTPException(404, "Task not found")
    allowed = {"open", "in_progress", "blocked", "completed", "cancelled"}
    if "status" in body and body["status"] not in allowed: raise HTTPException(422, "Invalid task state")
    if task.status == "completed" and body.get("status") not in (None, "completed"): raise HTTPException(409, "Completed tasks cannot transition")
    for key in ("status", "priority", "description", "title", "assigned_to"):
        if key in body: setattr(task, key, body[key])
    db.flush(); _record(db, "task.updated", user, {"id": task.id}); return _dump(task)


@app.post("/inventory/lots")
def create_lot(body: InventoryLotRequest, user: User = Depends(require_roles(Role.ADMIN, Role.MANAGER, Role.ANALYST)), db: Session = Depends(get_db)):
    item = InventoryLot(sku=body.sku, lot_number=body.lot_number, quantity=body.quantity, location=body.location)
    db.add(item); db.flush(); _record(db, "inventory.lot_created", user, {"id": item.id}); return _dump(item)


@app.post("/inventory/movements")
def create_movement(body: StockMovementRequest, user: User = Depends(require_roles(Role.ADMIN, Role.MANAGER, Role.ANALYST)), db: Session = Depends(get_db)):
    lot = db.get(InventoryLot, body.lot_id)
    if lot is None: raise HTTPException(404, "Inventory lot not found")
    if lot.status == "quarantined" and body.movement_type != "transfer": raise HTTPException(409, "Quarantined lots cannot move")
    delta = body.quantity if body.movement_type in ("receipt", "adjustment") else -body.quantity
    if lot.quantity + delta < 0: raise HTTPException(422, "Movement would make stock negative")
    lot.quantity += delta
    item = StockMovement(lot_id=lot.id, movement_type=body.movement_type, quantity=body.quantity, reason=body.reason, created_by=user.id)
    db.add(item); db.flush(); _record(db, "inventory.movement_created", user, {"id": item.id, "lot_id": lot.id}); return _dump(item, {"remaining_quantity": lot.quantity})


@app.get("/inventory/lots")
def list_lots(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [_dump(x) for x in db.scalars(select(InventoryLot).order_by(InventoryLot.id)).all()]


@app.post("/purchase-orders")
def create_purchase_order(body: PurchaseOrderRequest, user: User = Depends(require_roles(Role.ADMIN, Role.MANAGER)), db: Session = Depends(get_db)):
    if db.scalar(select(PurchaseOrder).where(PurchaseOrder.order_number == body.order_number)): raise HTTPException(409, "Order number already exists")
    order = PurchaseOrder(order_number=body.order_number, supplier_id=body.supplier_id, status=body.status, created_by=user.id)
    db.add(order); db.flush()
    for line in body.lines:
        if float(line.get("quantity", 0)) <= 0: raise HTTPException(422, "Line quantity must be positive")
        db.add(PurchaseOrderLine(purchase_order_id=order.id, sku=str(line["sku"]), quantity=float(line["quantity"]), unit_cost=float(line.get("unit_cost", 0))))
    db.flush(); _record(db, "purchase_order.created", user, {"id": order.id}); return _dump(order)


@app.get("/purchase-orders")
def list_purchase_orders(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [_dump(x) for x in db.scalars(select(PurchaseOrder).order_by(PurchaseOrder.id)).all()]


@app.post("/shipments")
def create_shipment(body: ShipmentRequest, user: User = Depends(require_roles(Role.ADMIN, Role.MANAGER, Role.ANALYST)), db: Session = Depends(get_db)):
    if body.purchase_order_id is not None and db.get(PurchaseOrder, body.purchase_order_id) is None: raise HTTPException(422, "Purchase order not found")
    item = Shipment(shipment_number=body.shipment_number, purchase_order_id=body.purchase_order_id, carrier=body.carrier, tracking_number=body.tracking_number, created_by=user.id)
    db.add(item); db.flush(); _record(db, "shipment.created", user, {"id": item.id, "purchase_order_id": body.purchase_order_id}); return _dump(item)


@app.get("/shipments")
def list_shipments(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [_dump(x) for x in db.scalars(select(Shipment).order_by(Shipment.id)).all()]


@app.post("/shipments/{shipment_id}/tracking-events")
def add_tracking_event(shipment_id: int, body: TrackingEventRequest, user: User = Depends(require_roles(Role.ADMIN, Role.MANAGER, Role.ANALYST)), db: Session = Depends(get_db)):
    if db.get(Shipment, shipment_id) is None: raise HTTPException(404, "Shipment not found")
    item = TrackingEvent(shipment_id=shipment_id, status=body.status, location=body.location, notes=body.notes)
    db.add(item); db.flush(); _record(db, "shipment.tracking_event", user, {"id": item.id}); return _dump(item)


@app.get("/shipments/{shipment_id}/tracking-events")
def list_tracking_events(shipment_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if db.get(Shipment, shipment_id) is None: raise HTTPException(404, "Shipment not found")
    return [_dump(x) for x in db.scalars(select(TrackingEvent).where(TrackingEvent.shipment_id == shipment_id).order_by(TrackingEvent.occurred_at)).all()]


@app.post("/quality/inspections")
def create_quality_inspection(body: QualityInspectionRequest, user: User = Depends(require_roles(Role.ADMIN, Role.MANAGER, Role.ANALYST)), db: Session = Depends(get_db)):
    lot = db.get(InventoryLot, body.lot_id)
    if lot is None: raise HTTPException(404, "Inventory lot not found")
    if body.result == "fail" and not body.quarantine_reason.strip(): raise HTTPException(422, "Failed inspections require quarantine reason")
    if body.result == "pass" and body.disposition is not None: raise HTTPException(422, "Passing inspection cannot have disposition")
    if body.result == "fail": lot.status = "quarantined"
    elif body.result == "pass": lot.status = "available"
    item = QualityInspection(lot_id=lot.id, result=body.result, quarantine_reason=body.quarantine_reason, disposition=body.disposition, inspected_by=user.id)
    db.add(item); db.flush(); _record(db, "quality.inspection_created", user, {"id": item.id, "lot_id": lot.id}); return _dump(item, {"lot_status": lot.status})


@app.post("/risks")
def create_risk(body: RiskRequest, user: User = Depends(require_roles(Role.ADMIN, Role.MANAGER)), db: Session = Depends(get_db)):
    item = Risk(title=body.title, description=body.description, likelihood=body.likelihood, impact=body.impact, owner_id=body.owner_id, created_by=user.id)
    db.add(item); db.flush(); _record(db, "risk.created", user, {"id": item.id}); return _dump(item)


@app.get("/risks")
def list_risks(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [_dump(x) for x in db.scalars(select(Risk).order_by(Risk.id)).all()]


@app.post("/documents")
def create_document(body: DocumentRequest, user: User = Depends(require_roles(Role.ADMIN, Role.MANAGER, Role.ANALYST)), db: Session = Depends(get_db)):
    item = Document(name=body.name, document_type=body.document_type, content_digest=body.content_digest,
                    metadata_json=json.dumps(body.metadata), created_by=user.id)
    db.add(item); db.flush(); _record(db, "document.created", user, {"id": item.id}); return _dump(item, {"metadata": body.metadata})


@app.get("/documents")
def list_documents(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [_dump(x, {"metadata": json.loads(x.metadata_json)}) for x in db.scalars(select(Document).order_by(Document.id)).all()]


@app.post("/control-tower/exceptions")
def create_exception(body: ExceptionRequest, user: User = Depends(require_roles(Role.ADMIN, Role.MANAGER)), db: Session = Depends(get_db)):
    item = ControlTowerException(title=body.title, severity=body.severity, category=body.category, details=body.details, assigned_to=body.assigned_to, created_by=user.id)
    db.add(item); db.flush(); _record(db, "control_tower.exception_created", user, {"id": item.id}); return _dump(item)


@app.get("/control-tower/exceptions")
def list_exceptions(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [_dump(x) for x in db.scalars(select(ControlTowerException).order_by(ControlTowerException.id)).all()]
