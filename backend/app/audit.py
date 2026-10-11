import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .models import AuditEvent, AuditWriteLock, utcnow

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


def acquire_audit_lock(db: Session):
    """Hold a singleton writer lock until transaction completion (SQLite/PG)."""
    dialect=db.get_bind().dialect.name
    if dialect=='sqlite':
        from sqlalchemy.dialects.sqlite import insert
    elif dialect=='postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:raise RuntimeError('Unsupported audit writer database')
    db.execute(insert(AuditWriteLock).values(id=1,value=0).on_conflict_do_nothing(index_elements=['id']))
    db.execute(update(AuditWriteLock).where(AuditWriteLock.id==1).values(value=AuditWriteLock.value+1))


def append_audit(db: Session, event_type: str, actor_id: int | None, payload: dict) -> AuditEvent:
    acquire_audit_lock(db)
    previous = db.scalar(select(AuditEvent).order_by(AuditEvent.sequence.desc()).limit(1))
    sequence = (previous.sequence + 1) if previous else 1
    previous_hash = previous.event_hash if previous else GENESIS_HASH
    created_at = utcnow()
    from .observability import context, sanitize
    from .models import PolicyState
    state = db.get(PolicyState, 1)
    payload = sanitize(dict(payload))
    payload['_context'] = {**context(), 'policy_revision_id': state.active_revision_id if state else None,
                           'policy_generation': state.generation if state else None}
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
    from .recommendation_history import project_audit as project_recommendation
    from .notifications.service import project_audit as project_notification
    project_recommendation(db, event, payload)
    project_notification(db, event, payload)
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
