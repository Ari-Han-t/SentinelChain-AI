from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import Role, User

password_hasher = PasswordHasher()
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        from .audit import append_audit
        append_audit(db, "auth.denied", None, {"outcome":"denied","reason":"missing_authentication"})
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        from .audit import append_audit
        append_audit(db, "auth.denied", None, {"outcome":"denied","reason":"invalid_authentication"})
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists")
    if not request.url.path.startswith("/security/policies"):
        from .policies import active_policy
        active_policy(db)
    return user


def require_roles(*roles: Role):
    allowed = {role.value for role in roles}

    def dependency(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        if user.role not in allowed:
            from .audit import append_audit
            append_audit(db, "access.role_denied", user.id, {"outcome":"denied", "operation":request.scope["route"].name})
            db.commit()
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        from .policies import effective_permissions
        permission = ROUTE_PERMISSIONS.get(request.scope["route"].name)
        if permission and permission not in effective_permissions(db, user.role):
            from .audit import append_audit
            from .policies import active_policy
            _, state = active_policy(db)
            append_audit(db, "policy.permission_denied", user.id, {"permission": permission, "revision_id": state.active_revision_id, "generation": state.generation, "outcome": "denied"})
            db.commit()
            raise HTTPException(403, "Published policy does not grant this permission")
        return user

    return dependency


# Immutable role capability ceilings. Published policy may restrict these grants.
# Route guards enforce the ceilings and current grants; clients consume effective grants.
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    Role.ADMIN.value: frozenset(
        {
            "chain.manage",
            "entity.manage",
            "inventory.manage", "procurement.manage", "logistics.manage",
            "node.manage",
            "edge.manage",
            "evidence.submit",
            "guidance.refresh",
            "forecast.manage",
            "recommendation.generate",
            "action.decide",
            "action.escalate",
            "node.verify",
            "audit.read",
            "org.manage",
            "demo.attack",
        }
    ),
    Role.ANALYST.value: frozenset(
        {
            "inventory.manage", "logistics.manage",
            "evidence.submit",
            "guidance.refresh",
            "forecast.manage",
            "recommendation.generate",
        }
    ),
    Role.MANAGER.value: frozenset(
        {
            "inventory.manage", "procurement.manage", "logistics.manage",
            "evidence.submit",
            "guidance.refresh",
            "action.decide",
            "action.escalate",
        }
    ),
    Role.AUDITOR.value: frozenset(
        {
            "guidance.refresh",
            "node.verify",
            "audit.read",
        }
    ),
}


def permissions_for(role: str) -> list[str]:
    return sorted(ROLE_PERMISSIONS.get(role, frozenset()))


def sign_import(content: bytes) -> str:
    return hmac.new(settings.import_hmac_secret.encode(), content, hashlib.sha256).hexdigest()


def verify_import_signature(content: bytes, signature: str) -> bool:
    return hmac.compare_digest(sign_import(content), signature.lower())


def _aes_key() -> bytes:
    return hashlib.sha256(settings.field_encryption_key.encode()).digest()


def encrypt_field(value: str) -> str:
    nonce = __import__("os").urandom(12)
    ciphertext = AESGCM(_aes_key()).encrypt(nonce, value.encode(), None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode()


def decrypt_field(value: str) -> str:
    raw = base64.urlsafe_b64decode(value.encode())
    return AESGCM(_aes_key()).decrypt(raw[:12], raw[12:], None).decode()



# Existing role ceilings stay in force; published policies may restrict them.
ROUTE_PERMISSIONS = {
    "security_audit_explore":"audit.read", "security_operations_overview":"audit.read", "simulation_history":"audit.read", "run_simulation":"demo.attack",
    "history_decision":"action.decide", "history_feedback":"action.decide",
    **{name: "entity.manage" for name in ("create_entity", "update_entity", "set_entity_state")},
    **{name: "chain.manage" for name in ("create_supply_chain", "update_supply_chain", "archive_supply_chain", "restore_supply_chain")},
    **{name: "node.manage" for name in ("create_node", "update_node", "deactivate_node", "activate_node", "create_node_template", "update_node_template", "delete_node_template")},
    **{name: "edge.manage" for name in ("create_edge", "update_edge", "delete_edge")},
    "ingest_event": "evidence.submit", "add_manual_event": "evidence.submit",
    "verify_node": "node.verify", "decide_action": "action.decide", "escalate_action": "action.escalate",
    "create_forecast": "forecast.manage", "ingest_import": "forecast.manage", "sign_dataset": "forecast.manage",
    "generate_recommendation": "recommendation.generate", "decide_recommendation": "action.decide",
    "audit_history": "audit.read", "run_attack": "demo.attack",
    "refresh_guidance": "guidance.refresh", "preview_import": "forecast.manage",
    "put_organization_context": "org.manage",
    "create_movement": "inventory.manage", "create_lot": "inventory.manage", "create_quality_inspection": "inventory.manage",
    "create_purchase_order": "procurement.manage", "create_shipment": "logistics.manage", "add_tracking_event": "logistics.manage",
}
