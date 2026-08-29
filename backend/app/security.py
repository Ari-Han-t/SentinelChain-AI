from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import Depends, HTTPException, status
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
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists")
    return user


def require_roles(*roles: Role):
    allowed = {role.value for role in roles}

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return dependency


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

