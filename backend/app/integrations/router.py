from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ..audit import append_audit
from ..config import settings
from ..database import get_db
from ..models import IntegrationConnection, IntegrationRun, IntegrationRecord, User, Role, utcnow
from ..security import get_current_user, require_roles
from .adapters import profiles, AdapterFailure
from .schemas import ConnectionInput, StateInput, RunInput, ApplyInput
from .service import connection_json, record_json, run_json, run_operation, apply_record

router=APIRouter(prefix="/integrations",tags=["External integrations"],dependencies=[Depends(require_roles(Role.ADMIN))])


def connection_or_404(db,id):
    connection=db.get(IntegrationConnection,id)
    if connection is None: raise HTTPException(404,"Integration connection not found")
    return connection


@router.get("/profiles")
def available_profiles():
    try:
        return {"profiles":[{"name":name,"system":profile.system} for name,profile in profiles().items()],
                "mock_allowed":settings.environment.lower()!="production"}
    except AdapterFailure as exc:
        raise HTTPException(503,exc.detail) from exc


@router.get("")
def connections(db:Session=Depends(get_db),limit:int=Query(100,ge=1,le=200),offset:int=Query(0,ge=0)):
    items=db.scalars(select(IntegrationConnection).order_by(IntegrationConnection.id).limit(limit).offset(offset)).all()
    return {"connections":[connection_json(x) for x in items],"total":db.scalar(select(func.count(IntegrationConnection.id)))}


@router.post("",status_code=201)
def create_connection(body:ConnectionInput,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    if body.mode=="mock" and settings.environment.lower()=="production": raise HTTPException(403,"Mock connections are disabled in production")
    if body.mode=="live":
        try: profile=profiles().get(body.profile)
        except AdapterFailure as exc: raise HTTPException(503,exc.detail) from exc
        if profile is None or profile.system!=body.system: raise HTTPException(422,"Select a matching configured backend profile")
    item=IntegrationConnection(**body.model_dump(exclude={"reason"}),created_by=user.id)
    db.add(item)
    try:
        db.flush()
        append_audit(db,"integration.connection_created",user.id,{"connection":connection_json(item),"reason":body.reason})
        db.commit()
    except IntegrityError as exc:
        db.rollback();raise HTTPException(409,"Connection name already exists") from exc
    return connection_json(item)


@router.post("/{id}/state")
def set_connection_state(id:int,body:StateInput,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    connection=connection_or_404(db,id);now=utcnow()
    before=connection_json(connection)
    result=db.execute(update(IntegrationConnection).where(IntegrationConnection.id==id,IntegrationConnection.version==body.expected_version,
                      (IntegrationConnection.lease_until.is_(None)) | (IntegrationConnection.lease_until<=now))
                     .values(enabled=body.enabled,version=IntegrationConnection.version+1))
    if result.rowcount!=1: raise HTTPException(409,"Connection changed or is running; reload before changing state")
    db.refresh(connection)
    append_audit(db,"integration.connection_state",user.id,{"connection_id":id,"before":before,"after":connection_json(connection),"reason":body.reason})
    db.commit();return connection_json(connection)


@router.post("/{id}/check")
def check_connection(id:int,body:RunInput,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    return run_operation(db,user,connection_or_404(db,id),"check",body)


@router.post("/{id}/sync")
def sync_connection(id:int,body:RunInput,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    return run_operation(db,user,connection_or_404(db,id),"sync",body)


@router.get("/{id}/runs")
def run_history(id:int,db:Session=Depends(get_db),limit:int=Query(30,ge=1,le=200),offset:int=Query(0,ge=0)):
    connection_or_404(db,id)
    statement=select(IntegrationRun).where(IntegrationRun.connection_id==id).order_by(IntegrationRun.started_at.desc()).limit(limit).offset(offset)
    return [run_json(x) for x in db.scalars(statement)]


@router.get("/{id}/records")
def records(id:int,db:Session=Depends(get_db),q:str=Query("",max_length=120),resource:str|None=None,review_status:str=Query("all",pattern="^(all|pending_review|imported)$"),limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0)):
    connection_or_404(db,id)
    statement=select(IntegrationRecord).where(IntegrationRecord.connection_id==id)
    if q: statement=statement.where(IntegrationRecord.external_id.contains(q,autoescape=True))
    if resource: statement=statement.where(IntegrationRecord.resource==resource)
    if review_status=="imported": statement=statement.where(IntegrationRecord.applied_version==IntegrationRecord.source_version)
    elif review_status=="pending_review": statement=statement.where((IntegrationRecord.applied_version.is_(None)) | (IntegrationRecord.applied_version!=IntegrationRecord.source_version))
    total=db.scalar(select(func.count()).select_from(statement.subquery()))
    items=db.scalars(statement.order_by(IntegrationRecord.id).limit(limit).offset(offset)).all()
    return {"records":[record_json(db,x) for x in items],"total":total}


@router.get("/{id}/records/{record_id}")
def record_detail(id:int,record_id:int,db:Session=Depends(get_db)):
    connection_or_404(db,id);item=db.get(IntegrationRecord,record_id)
    if item is None or item.connection_id!=id: raise HTTPException(404,"Integration record not found")
    return record_json(db,item)


@router.post("/{id}/records/{record_id}/apply")
def import_record(id:int,record_id:int,body:ApplyInput,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    connection_or_404(db,id);item=db.get(IntegrationRecord,record_id)
    if item is None or item.connection_id!=id: raise HTTPException(404,"Integration record not found")
    return apply_record(db,user,record_id,body)
