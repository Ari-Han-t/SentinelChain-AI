from ..models import utc_naive
from datetime import timedelta, timezone
import hashlib
import json
import uuid
from fastapi import HTTPException
from sqlalchemy import select, update, or_
from sqlalchemy.exc import IntegrityError
from ..audit import append_audit
from ..models import (IntegrationConnection, IntegrationRun, IntegrationRecord, IntegrationEvent,
                      EntityGovernance, StockMovement, TrackingEvent, Shipment, utcnow)
from ..security import encrypt_field, decrypt_field
from ..entities import MODELS, EntityInput, GovernanceInput, entity_json, save_entity, entity_or_404, guard
from .adapters import adapter_for, AdapterFailure
from .schemas import ApplyInput


def run_json(run, duplicate=False):
    return {column.name:getattr(run,column.name) for column in run.__table__.columns} | {"duplicate_request":duplicate}


def connection_json(connection):
    now = utcnow()
    stale = connection.synced_at is not None and utc_naive(connection.synced_at) + timedelta(seconds=connection.stale_after_seconds) <= now
    return {name:getattr(connection,name) for name in ("id","name","system","mode","profile","enabled","mock_scenario","stale_after_seconds","version","health","checked_at","synced_at","retry_at","created_at")} | {
        "stale":stale, "busy": bool(connection.lease_until and utc_naive(connection.lease_until) > now),
        "provenance":"mock" if connection.mode == "mock" else "live",
        "data_state":"stale" if stale else "not_synchronized" if connection.synced_at is None else "mock" if connection.mode == "mock" else "synchronized",
        "has_more":connection.cursor is not None}


def record_json(db, record):
    connection = db.get(IntegrationConnection,record.connection_id)
    data = json.loads(decrypt_field(record.encrypted_data))
    data.pop("contact",None)
    version = None
    if record.entity_id and record.resource in MODELS:
        governance = db.scalar(select(EntityGovernance).where(EntityGovernance.kind==record.resource,EntityGovernance.entity_id==record.entity_id))
        version = governance.version if governance else 1
    return {name:getattr(record,name) for name in ("id","connection_id","resource","external_id","source_version","provenance","occurred_at","received_at","run_id","entity_id","applied_version","applied_at")} | {
        "data":data, "stale":record.received_at + timedelta(seconds=connection.stale_after_seconds) <= utcnow(),
        "review_status":"imported" if record.applied_version==record.source_version else "pending_review",
        "entity_version":version}


def payload_digest(record, include_event=False):
    payload = record.model_dump(mode="json")
    if not include_event: payload.pop("event_id")
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def ingest_page(db, connection, run, page):
    for incoming in page.records:
        event_digest = payload_digest(incoming, True)
        previous_event = db.scalar(select(IntegrationEvent).where(IntegrationEvent.connection_id==connection.id,IntegrationEvent.event_id==incoming.event_id))
        record = db.scalar(select(IntegrationRecord).where(IntegrationRecord.connection_id==connection.id,IntegrationRecord.resource==incoming.resource,IntegrationRecord.external_id==incoming.external_id).with_for_update().execution_options(populate_existing=True))
        digest = payload_digest(incoming)
        if previous_event:
            if previous_event.digest != event_digest:
                raise AdapterFailure("replay_conflict","An event identifier was replayed with different content", attempts=run.attempts)
            if record and record.source_version == incoming.source_version and record.digest == digest:
                record.received_at = utcnow()
            run.duplicates += 1
            continue
        outcome = "accepted"
        if record and incoming.source_version < record.source_version:
            run.ignored += 1; outcome = "out_of_order"
        elif record and incoming.source_version == record.source_version:
            if record.digest != digest:
                raise AdapterFailure("version_conflict","An external record version has conflicting content", attempts=run.attempts)
            record.received_at = utcnow()
            run.duplicates += 1; outcome = "duplicate"
        else:
            if record is None:
                record = IntegrationRecord(connection_id=connection.id,resource=incoming.resource,external_id=incoming.external_id)
                db.add(record)
            record.source_version = incoming.source_version
            record.digest = digest
            record.encrypted_data = encrypt_field(json.dumps(incoming.data,sort_keys=True))
            record.provenance = "mock" if connection.mode == "mock" else "synchronized"
            record.occurred_at = incoming.occurred_at.astimezone(timezone.utc).replace(tzinfo=None)
            record.received_at = utcnow(); record.run_id = run.id
            run.accepted += 1
        db.add(IntegrationEvent(connection_id=connection.id,event_id=incoming.event_id,digest=event_digest,outcome=outcome,run_id=run.id))
        db.flush()


def run_operation(db, user, connection, operation, body):
    existing = db.scalar(select(IntegrationRun).where(IntegrationRun.connection_id==connection.id,IntegrationRun.idempotency_key==body.idempotency_key))
    if existing:
        if existing.operation != operation:
            raise HTTPException(409,"Idempotency key belongs to another operation")
        return run_json(existing,True)
    now = utcnow()
    if not connection.enabled: raise HTTPException(409,"Enable this connection before running it")
    if connection.retry_at and utc_naive(connection.retry_at) > now: raise HTTPException(429,"Partner cooldown is active; retry after the displayed retry time")
    run_id = str(uuid.uuid4())
    previous_owner = connection.lease_owner
    lease = db.execute(update(IntegrationConnection).where(IntegrationConnection.id==connection.id,IntegrationConnection.enabled.is_(True),
                        or_(IntegrationConnection.lease_until.is_(None),IntegrationConnection.lease_until<=now))
                       .values(lease_owner=run_id,lease_until=now+timedelta(seconds=120)))
    if lease.rowcount != 1: raise HTTPException(409,"Another integration run is in progress")
    if previous_owner:
        previous_run = db.get(IntegrationRun, previous_owner)
        if previous_run and previous_run.status == "running":
            previous_run.status="failed";previous_run.finished_at=now
            previous_run.error_code="interrupted";previous_run.error_detail="Previous run lease expired; retry with a new request key"
    run = IntegrationRun(id=run_id,connection_id=connection.id,idempotency_key=body.idempotency_key,operation=operation,requested_by=user.id,reason=body.reason)
    db.add(run)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(IntegrationRun).where(IntegrationRun.connection_id==connection.id,IntegrationRun.idempotency_key==body.idempotency_key))
        if existing: return run_json(existing,True)
        raise HTTPException(409,"Concurrent integration request; reload and retry")
    append_audit(db,"integration.run_started",user.id,{"connection_id":connection.id,"run_id":run_id,"operation":operation,"mode":connection.mode,"reason":body.reason})
    db.commit()
    attempts = 0
    failure = None
    page = None
    try:
        adapter = adapter_for(connection)
        if operation == "check": adapter.check()
        else: page = adapter.pull(connection.cursor)
        attempts = adapter.attempts
        db.expire_all()
        connection = db.scalar(select(IntegrationConnection).where(IntegrationConnection.id==connection.id).with_for_update())
        run = db.get(IntegrationRun,run_id)
        if connection.lease_owner != run_id or connection.lease_until <= utcnow():
            raise AdapterFailure("interrupted","Run lease expired before synchronization could commit",attempts=attempts)
        run.attempts = attempts
        if page is not None:
            ingest_page(db,connection,run,page)
            connection.cursor = page.next_cursor
            connection.synced_at = utcnow()
        connection.checked_at = utcnow()
        connection.health = "mock_ready" if connection.mode == "mock" else "reachable"
        connection.retry_at = None
        run.status = "succeeded"
    except AdapterFailure as exc:
        failure = exc
    except IntegrityError:
        failure = AdapterFailure("conflict","Concurrent or conflicting integration records; no inbox changes were committed",attempts=attempts)
    if failure:
        db.rollback()
        connection = db.scalar(select(IntegrationConnection).where(IntegrationConnection.id==connection.id).with_for_update())
        run = db.get(IntegrationRun,run_id)
        # A timed-out worker cannot take ownership back from a newer run.
        if connection.lease_owner != run_id:
            return run_json(run)
        connection.health = "rate_limited" if failure.code=="rate_limited" else "failed"
        connection.checked_at = utcnow()
        connection.retry_at = utcnow()+timedelta(seconds=failure.retry_after) if failure.retry_after is not None else None
        run.status="failed";run.attempts=failure.attempts
        run.error_code=failure.code;run.error_detail=failure.detail
        run.accepted=0;run.duplicates=0;run.ignored=0
    run.finished_at = utcnow()
    connection.lease_owner=None;connection.lease_until=None
    append_audit(db,"integration.run_finished",user.id,{"connection_id":connection.id,"run_id":run.id,"operation":operation,"mode":connection.mode,"status":run.status,
                  "attempts":run.attempts,"accepted":run.accepted,"duplicates":run.duplicates,"ignored":run.ignored,"error_code":run.error_code,"reason":body.reason})
    db.commit()
    return run_json(run)


def mapped_parent(db, record, external_id, resource):
    if external_id is None: return None
    parent = db.scalar(select(IntegrationRecord).where(IntegrationRecord.connection_id==record.connection_id,IntegrationRecord.resource==resource,IntegrationRecord.external_id==external_id))
    if parent and parent.entity_id and parent.applied_version is not None:
        return parent.entity_id
    raise HTTPException(422,"Related external record is not imported; select an existing local parent or import the related record first")


def apply_record(db, user, record_id, body: ApplyInput):
    record = db.scalar(select(IntegrationRecord).where(IntegrationRecord.id==record_id).with_for_update().execution_options(populate_existing=True))
    if record is None: raise HTTPException(404,"Integration record not found")
    connection = db.get(IntegrationConnection,record.connection_id)
    if record.provenance != "synchronized" or connection.mode != "live":
        raise HTTPException(403,"Mock records cannot be imported into operational data")
    if not connection.enabled: raise HTTPException(409,"Connection is disabled; imports are paused")
    if record.received_at + timedelta(seconds=connection.stale_after_seconds) <= utcnow():
        raise HTTPException(409,"Record is stale; synchronize and review again")
    if record.source_version != body.expected_source_version: raise HTTPException(409,"Source record changed; reload and review again")
    if record.applied_version == record.source_version:
        return {"record_id":record.id,"entity_id":record.entity_id,"duplicate_request":True}
    data = json.loads(decrypt_field(record.encrypted_data))
    resource = record.resource
    if resource in ("stock-movements","tracking-events"):
        if record.applied_version is not None: raise HTTPException(409,"Imported events are immutable; use a new corrective external event")
        if body.target_entity_id is not None: raise HTTPException(422,"Event records require a parent, not an existing event target")
        parent_kind = "inventory" if resource=="stock-movements" else "shipments"
        external_key = "lot_external_id" if resource=="stock-movements" else "shipment_external_id"
        parent_id = body.parent_entity_id or mapped_parent(db,record,data[external_key],parent_kind)
        parent = db.scalar(select(MODELS[parent_kind]).where(MODELS[parent_kind].id==parent_id).with_for_update().execution_options(populate_existing=True))
        if parent is None: raise HTTPException(404,"Related entity not found")
        guard(db,user,parent_kind,parent_id,True)
        if body.expected_entity_version != entity_json(db,parent_kind,parent)["version"]:
            raise HTTPException(409,"Parent record changed; reload before importing")
        if resource=="stock-movements":
            from ..inventory_ops import apply_movement
            from ..schemas import StockMovementRequest
            result = apply_movement(db,user,StockMovementRequest(lot_id=parent_id,movement_type=data["movement_type"],quantity=data["quantity"],reason=body.reason[:300]))
            entity_id = result.id
        else:
            result=TrackingEvent(shipment_id=parent_id,status=data["status"],location=data["location"],notes=data["notes"],occurred_at=record.occurred_at)
            db.add(result);db.flush();entity_id=result.id
            append_audit(db,"shipment.tracking_added",user.id,{"id":entity_id,"shipment_id":parent_id,"integration_record_id":record.id})
    else:
        target_id = record.entity_id or body.target_entity_id
        if record.entity_id and body.target_entity_id not in (None,record.entity_id):
            raise HTTPException(409,"An imported identity cannot be remapped to another entity")
        target = db.scalar(select(MODELS[resource]).where(MODELS[resource].id==target_id).with_for_update().execution_options(populate_existing=True)) if target_id else None
        if target_id and target is None: raise HTTPException(404,"Target entity not found")
        if target:
            current = entity_json(db,resource,target)
            governance = GovernanceInput(**current["governance"])
            if body.expected_entity_version != current["version"]: raise HTTPException(409,"Local entity changed; reload before importing")
        else:
            if body.expected_entity_version is not None: raise HTTPException(422,"New entities do not have a local version")
            governance=GovernanceInput()
        if resource=="suppliers":
            compliance=data.pop("compliance_status"); identity=data.pop("identity_status")
            if compliance=="non_compliant" or identity=="disputed": governance.risk_level="critical"
        if resource=="purchase-orders":
            external=data.pop("supplier_external_id")
            data["supplier_id"]=body.parent_entity_id or mapped_parent(db,record,external,"suppliers")
        elif resource=="inventory":
            external=data.pop("warehouse_external_id")
            governance.warehouse_id=body.parent_entity_id or mapped_parent(db,record,external,"warehouses")
        elif resource=="shipments":
            external=data.pop("purchase_order_external_id")
            data["purchase_order_id"]=body.parent_entity_id or mapped_parent(db,record,external,"purchase-orders")
            data.pop("reported_status");data.pop("estimated_arrival")
        elif body.parent_entity_id is not None:
            raise HTTPException(422,"This resource does not accept a parent assignment")
        result=save_entity(db,user,resource,EntityInput(data=data,governance=governance,expected_version=body.expected_entity_version,reason=body.reason),target,commit=False)
        entity_id=result["id"]
    record.entity_id=entity_id;record.applied_version=record.source_version;record.applied_at=utcnow()
    append_audit(db,"integration.record_imported",user.id,{"record_id":record.id,"connection_id":record.connection_id,"resource":record.resource,"entity_id":entity_id,"source_version":record.source_version,"run_id":record.run_id,"provenance":record.provenance,"reason":body.reason})
    db.commit()
    return {"record_id":record.id,"entity_id":entity_id,"duplicate_request":False}
