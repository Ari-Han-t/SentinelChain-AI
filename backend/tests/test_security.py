from sqlalchemy import select

from app.audit import verify_chain
from app.database import SessionLocal
from app.models import AuditEvent
from app.security import decrypt_field, encrypt_field, sign_import, verify_import_signature


def test_hmac_rejects_modified_content():
    original = b"sku,date,quantity\nSKU-001,2026-01-01,20\n"
    signature = sign_import(original)
    assert verify_import_signature(original, signature)
    assert not verify_import_signature(original.replace(b",20", b",200"), signature)


def test_aes_gcm_round_trip_and_random_nonce():
    first = encrypt_field("supplier@example.com")
    second = encrypt_field("supplier@example.com")
    assert first != second
    assert decrypt_field(first) == "supplier@example.com"


def test_audit_chain_detects_database_tampering():
    with SessionLocal() as db:
        assert verify_chain(db) == (True, None)
        event = db.scalar(select(AuditEvent).order_by(AuditEvent.sequence))
        event.payload_json = '{"tampered":true}'
        db.commit()
        valid, broken_at = verify_chain(db)
        assert not valid
        assert broken_at == 1


def test_protected_route_requires_authentication(client):
    response = client.get("/dashboard")
    assert response.status_code == 401


def test_role_cannot_cross_approval_boundary(client, auth):
    response = client.post(
        "/recommendations/1/decision",
        headers=auth("analyst"),
        json={"decision": "approved", "expected_status": "pending"},
    )
    assert response.status_code == 403

