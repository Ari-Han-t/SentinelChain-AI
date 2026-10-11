"""Typed, deterministic policy snapshots. Drafts never influence authorization."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .audit import append_audit
from .database import get_db
from .models import PolicyRevision, PolicyState, User, Role, utcnow
from .security import get_current_user, ROLE_PERMISSIONS

KINDS = ("suppliers", "warehouses", "products", "inventory", "purchase-orders", "shipments")
OPERATIONS = ("inventory.change", "supplier.update", "forecast.modify", "approval.decide")
CLEARANCES = {"administrator": 4, "procurement_manager": 3, "inventory_analyst": 2, "auditor": 1}
router = APIRouter(prefix="/security/policies", tags=["Policy administration"])


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class Rule(Strict):
    key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    operation: Literal["inventory.change", "supplier.update", "forecast.modify", "approval.decide"]
    priority: int = Field(default=100, ge=0, le=1000)
    active: bool = True
    minimum_clearance: int = Field(default=1, ge=1, le=4)
    deny_at_risk: Literal["none", "low", "medium", "high", "critical"] = "none"
    max_quantity_delta: int | None = Field(default=None, ge=0, le=1000000000)
    effective_from: datetime | None = None
    effective_until: datetime | None = None

    @model_validator(mode="after")
    def valid(self):
        for value in (self.effective_from, self.effective_until):
            if value is not None and value.tzinfo is None:
                raise ValueError("Effective dates must include a timezone")
        if self.effective_from and self.effective_until and self.effective_from >= self.effective_until:
            raise ValueError("Effective end must be after the start")
        if self.max_quantity_delta is not None and self.operation != "inventory.change":
            raise ValueError("Quantity limits apply only to inventory changes")
        return self


class Configuration(Strict):
    role_permissions: dict[str, list[str]]
    entity_clearance: dict[str, int]
    operation_clearance: dict[str, int]
    approval_quantity_threshold: int = Field(default=1000000000, ge=0, le=1000000000)
    approval_risk_threshold: float = Field(default=100, ge=0, le=100)
    rules: list[Rule] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def valid(self):
        if set(self.role_permissions) != set(ROLE_PERMISSIONS):
            raise ValueError("Every existing role must have an explicit permission assignment")
        for role, permissions in self.role_permissions.items():
            if len(permissions) != len(set(permissions)) or not set(permissions) <= ROLE_PERMISSIONS[role]:
                raise ValueError(f"Invalid or escalated permissions for {role}")
        if set(self.role_permissions[Role.ADMIN.value]) != ROLE_PERMISSIONS[Role.ADMIN.value]:
            raise ValueError("Administrator capabilities are protected to preserve policy recovery")
        for values, keys in ((self.entity_clearance, KINDS), (self.operation_clearance, OPERATIONS)):
            if set(values) != set(keys) or any(type(x) is not int or not 1 <= x <= 4 for x in values.values()):
                raise ValueError("Every clearance requirement must be an integer between 1 and 4")
        if len({r.key for r in self.rules}) != len(self.rules):
            raise ValueError("Rule identifiers must be unique")
        return self


class DraftInput(Strict):
    configuration: Configuration
    expected_generation: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=1000)


class PublishInput(Strict):
    expected_generation: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=1000)


class Assignment(Strict):
    role: Role
    expected_role: Role
    reason: str = Field(min_length=3, max_length=1000)


def canonical(config):
    return json.dumps(config.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def default_configuration():
    return Configuration(role_permissions={r: sorted(p) for r, p in ROLE_PERMISSIONS.items()},
                         entity_clearance={k: 1 for k in KINDS},
                         operation_clearance={k: 1 for k in OPERATIONS})


def initialize_policy(db):
    # Startup provisioning only. Never silently recover missing/corrupt runtime state.
    if db.get(PolicyState, 1) is None:
        if db.scalar(select(PolicyRevision.id).limit(1)) is not None:
            raise RuntimeError("Policy pointer is missing; administrator recovery is required")
        content = canonical(default_configuration())
        revision = PolicyRevision(configuration_json=content, digest=hashlib.sha256(content.encode()).hexdigest(),
                                  status="published", base_generation=0, reason="Initial built-in security policy", published_at=utcnow())
        db.add(revision); db.flush()
        db.add(PolicyState(id=1, active_revision_id=revision.id, generation=1)); db.flush()
        append_audit(db, "policy.initialized", None, {"revision_id": revision.id, "configuration": json.loads(content)})
        db.commit()


def configuration_for(revision):
    try:
        if revision is None or hashlib.sha256(revision.configuration_json.encode()).hexdigest() != revision.digest:
            raise ValueError("Integrity mismatch")
        return Configuration.model_validate_json(revision.configuration_json)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(503, "Security policy is invalid; contact an administrator") from exc


def active_policy(db):
    state = db.get(PolicyState, 1)
    revision = db.get(PolicyRevision, state.active_revision_id) if state else None
    if revision is None or revision.status != "published":
        raise HTTPException(503, "Security policy is unavailable; contact an administrator")
    return configuration_for(revision), state


def effective_permissions(db, role):
    config, _ = active_policy(db)
    return config.role_permissions.get(role, [])


def entity_level(db, kind):
    config, _ = active_policy(db)
    return config.entity_clearance[kind]


def enforce(db, user, operation, *, risk="low", quantity_delta=0, recommendation=None):
    config, state = active_policy(db)
    level = CLEARANCES.get(user.role, 0)
    now = datetime.now(timezone.utc)
    ranks = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    reason = None
    matched = []
    if level < config.operation_clearance[operation]:
        reason = "Operation clearance requirement is not met"
    for rule in sorted(config.rules, key=lambda r: (r.priority, r.key)):
        if rule.operation != operation or not rule.active:
            continue
        if rule.effective_from and now < rule.effective_from or rule.effective_until and now >= rule.effective_until:
            continue
        matched.append(rule.key)
        if level < rule.minimum_clearance:
            reason = f"Rule {rule.key}: clearance requirement is not met"
        if rule.deny_at_risk != "none" and ranks.get(risk, 4) >= ranks[rule.deny_at_risk]:
            reason = f"Rule {rule.key}: risk restriction blocks this operation"
        if rule.max_quantity_delta is not None and abs(quantity_delta) > rule.max_quantity_delta:
            reason = f"Rule {rule.key}: inventory change exceeds the permitted quantity"
    if recommendation is not None and user.role != Role.ADMIN.value:
        if recommendation.recommended_quantity >= config.approval_quantity_threshold or recommendation.supplier_risk >= config.approval_risk_threshold:
            reason = "Approval exceeds the administrator quantity or supplier-risk threshold"
    payload = {"operation": operation, "revision_id": state.active_revision_id, "generation": state.generation,
               "matched_rules": matched, "outcome": "denied" if reason else "allowed", "reason": reason}
    append_audit(db, "policy.evaluated", user.id, payload)
    if reason:
        # Evaluation occurs before writes; retain denied decisions in the ledger.
        db.commit()
        raise HTTPException(403, reason)


def admin(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Immutable root authority: a configurable role cannot grant policy administration.
    if user.role != Role.ADMIN.value:
        append_audit(db, "access.role_denied", user.id, {"outcome":"denied", "operation":"policy.administration", "reason":"administrator_required"})
        db.commit()
        raise HTTPException(403, "Only administrators may configure, publish, or revert policies")
    return user


def revision_json(item):
    return {"id": item.id, "configuration": configuration_for(item).model_dump(mode="json"),
            "status": item.status, "base_generation": item.base_generation, "digest": item.digest,
            "created_by": item.created_by, "created_at": item.created_at, "reason": item.reason,
            "published_by": item.published_by, "published_at": item.published_at}


@router.get("")
def overview(user: User = Depends(admin), db: Session = Depends(get_db)):
    config, state = active_policy(db)
    return {"generation": state.generation, "active_revision_id": state.active_revision_id,
            "configuration": config.model_dump(mode="json"), "permission_ceiling": {r: sorted(p) for r, p in ROLE_PERMISSIONS.items()},
            "clearance_levels": CLEARANCES,
            "revisions": [revision_json(x) for x in db.scalars(select(PolicyRevision).order_by(PolicyRevision.id.desc()))],
            "users": [{"id": x.id, "display_name": x.display_name, "role": x.role} for x in db.scalars(select(User).order_by(User.id))]}


@router.post("/drafts", status_code=201)
def create_draft(body: DraftInput, user: User = Depends(admin), db: Session = Depends(get_db)):
    _, state = active_policy(db)
    if state.generation != body.expected_generation:
        raise HTTPException(409, "Published policy changed; reload before drafting")
    content = canonical(body.configuration)
    item = PolicyRevision(configuration_json=content, digest=hashlib.sha256(content.encode()).hexdigest(),
                          base_generation=state.generation, created_by=user.id, reason=body.reason)
    db.add(item); db.flush()
    append_audit(db, "policy.drafted", user.id, {"revision_id": item.id, "before": configuration_for(db.get(PolicyRevision, state.active_revision_id)).model_dump(mode="json"),
                                               "after": body.configuration.model_dump(mode="json"), "reason": body.reason})
    db.commit()
    return revision_json(item)


def activate(db, user, item, expected_generation, reason, event):
    configuration_for(item)
    state = db.get(PolicyState, 1)
    if state is None:
        raise HTTPException(503, "Security policy pointer is unavailable")
    old = db.get(PolicyRevision, state.active_revision_id)
    before = configuration_for(old).model_dump(mode="json")
    result = db.execute(update(PolicyState).where(PolicyState.id == 1, PolicyState.generation == expected_generation)
                        .values(active_revision_id=item.id, generation=expected_generation + 1))
    if result.rowcount != 1:
        raise HTTPException(409, "Published policy changed; reload and review again")
    item.status = "published"; item.published_by = user.id; item.published_at = utcnow()
    append_audit(db, event, user.id, {"previous_revision_id": old.id, "revision_id": item.id,
                                    "generation": expected_generation + 1, "before": before,
                                    "after": configuration_for(item).model_dump(mode="json"), "reason": reason})
    db.commit()
    return {"generation": expected_generation + 1, "active_revision_id": item.id}


@router.post("/{revision_id}/publish")
def publish(revision_id: int, body: PublishInput, user: User = Depends(admin), db: Session = Depends(get_db)):
    item = db.scalar(select(PolicyRevision).where(PolicyRevision.id == revision_id).with_for_update())
    if item is None: raise HTTPException(404, "Policy revision not found")
    if item.status != "draft": raise HTTPException(409, "Only a draft can be published")
    if item.base_generation != body.expected_generation: raise HTTPException(409, "Draft is stale; create and review a new draft")
    return activate(db, user, item, body.expected_generation, body.reason, "policy.published")


@router.post("/{revision_id}/revert")
def revert(revision_id: int, body: PublishInput, user: User = Depends(admin), db: Session = Depends(get_db)):
    original = db.get(PolicyRevision, revision_id)
    if original is None: raise HTTPException(404, "Policy revision not found")
    if original.status != "published": raise HTTPException(409, "Only a previously published revision can be restored")
    content = canonical(configuration_for(original))
    item = PolicyRevision(configuration_json=content, digest=hashlib.sha256(content.encode()).hexdigest(),
                          base_generation=body.expected_generation, created_by=user.id,
                          reason=f"Restore revision {revision_id}: {body.reason}")
    db.add(item); db.flush()
    return activate(db, user, item, body.expected_generation, body.reason, "policy.reverted")


@router.post("/users/{user_id}/role")
def assign_role(user_id: int, body: Assignment, user: User = Depends(admin), db: Session = Depends(get_db)):
    # Serialize assignments on the same singleton used by publication.
    db.scalar(select(PolicyState).where(PolicyState.id == 1).with_for_update())
    active_policy(db)
    db.refresh(user)
    if user.role != Role.ADMIN.value:
        raise HTTPException(403, "Administrator authority changed; sign in again")
    target = db.get(User, user_id)
    if target is None: raise HTTPException(404, "User not found")
    if target.role != body.expected_role.value: raise HTTPException(409, "User role changed; reload before assigning")
    if target.id == user.id: raise HTTPException(409, "Administrators cannot change their own role")
    previous = target.role
    target.role = body.role.value
    append_audit(db, "policy.role_assigned", user.id, {"user_id": target.id, "before": previous, "after": target.role, "reason": body.reason})
    db.commit()
    return {"id": target.id, "role": target.role}
