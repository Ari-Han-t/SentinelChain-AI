import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import AuditEvent, utcnow

GENESIS_HASH = "0" * 64


def _canonical_timestamp(created_at: datetime) -> str:
    """Keep audit hashes stable across SQLite and PostgreSQL timezone handling."""
    if created_at.tzinfo is not None:
        created_at = created_at.astimezone(timezone.utc).replace(tzinfo=None)
    return created_at.isoformat()


def _canonical_event(sequence: int, event_type: str, actor_id: int | None, payload_json: str, created_at: datetime, previous_hash: str) -> bytes:
    return json.dumps(
        {
            "sequence": sequence,
            "event_type": event_type,
            "actor_id": actor_id,
            "payload": json.loads(payload_json),
            "created_at": _canonical_timestamp(created_at),
            "previous_hash": previous_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def append_audit(db: Session, event_type: str, actor_id: int | None, payload: dict) -> AuditEvent:
    previous = db.scalar(select(AuditEvent).order_by(AuditEvent.sequence.desc()).limit(1))
    sequence = (previous.sequence + 1) if previous else 1
    previous_hash = previous.event_hash if previous else GENESIS_HASH
    created_at = utcnow()
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(
        _canonical_event(sequence, event_type, actor_id, payload_json, created_at, previous_hash)
    ).hexdigest()
    event = AuditEvent(
        sequence=sequence,
        event_type=event_type,
        actor_id=actor_id,
        payload_json=payload_json,
        previous_hash=previous_hash,
        event_hash=digest,
        created_at=created_at,
    )
    db.add(event)
    db.flush()
    return event


def verify_chain(db: Session) -> tuple[bool, int | None]:
    previous_hash = GENESIS_HASH
    events = db.scalars(select(AuditEvent).order_by(AuditEvent.sequence)).all()
    for expected_sequence, event in enumerate(events, start=1):
        expected = hashlib.sha256(
            _canonical_event(
                event.sequence,
                event.event_type,
                event.actor_id,
                event.payload_json,
                event.created_at,
                event.previous_hash,
            )
        ).hexdigest()
        if event.sequence != expected_sequence or event.previous_hash != previous_hash or event.event_hash != expected:
            return False, event.sequence
        previous_hash = event.event_hash
    return True, None


def audit_count(db: Session) -> int:
    return int(db.scalar(select(func.count(AuditEvent.id))) or 0)
