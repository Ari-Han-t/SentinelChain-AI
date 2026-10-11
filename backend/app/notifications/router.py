from ..models import utc_naive
import json
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select,update
from ..database import get_db
from ..models import NotificationRule,Incident,IncidentHistory,NotificationDelivery,User,Role,utcnow
from ..security import get_current_user,require_roles
from ..audit import append_audit,acquire_audit_lock
from .service import CATEGORIES,SEVERITIES,can_access,history,notify,reconcile,initialize_rules

router=APIRouter(tags=['notifications'])
admin=require_roles(Role.ADMIN)

def incident_json(db,item,detail=False):
    data={c.name:getattr(item,c.name) for c in item.__table__.columns if c.name!='dedup_key'}
    if item.category=='pending_approval' and item.status=='resolved' and (item.resolution_note or '').startswith('Source recommendation decision:'):
        data['title']='Closed approval request'
        data['detail']=item.resolution_note+'. This historical notification no longer requires a pending decision.'
    data['overdue']=item.status!='resolved' and utc_naive(item.due_at)<=utcnow()
    data['assigned_user_name']=db.get(User,item.assigned_user_id).display_name if item.assigned_user_id and db.get(User,item.assigned_user_id) else None
    if detail:
        data['history']=[{'id':row.id,'event_type':row.event_type,'actor_id':row.actor_id,'actor_name':db.get(User,row.actor_id).display_name if row.actor_id and db.get(User,row.actor_id) else 'System','created_at':row.created_at,'detail':json.loads(row.detail_json)} for row in db.scalars(select(IncidentHistory).where(IncidentHistory.incident_id==item.id).order_by(IncidentHistory.id)).all()]
    return data


def get_incident(db,user,id,lock=False):
    item=db.scalar(select(Incident).where(Incident.id==id).with_for_update().execution_options(populate_existing=True)) if lock else db.get(Incident,id)
    if item is None or not can_access(db,user,item):raise HTTPException(404,'Incident not found or outside your access scope')
    return item


@router.get('/notifications')
def notifications(unread:bool=False,offset:int=Query(default=0,ge=0),limit:int=Query(default=30,ge=1,le=100),user:User=Depends(get_current_user),db=Depends(get_db)):
    rows=[];unread_count=0
    for row in db.scalars(select(NotificationDelivery).where(NotificationDelivery.user_id==user.id,NotificationDelivery.status=='delivered').order_by(NotificationDelivery.created_at.desc())).all():
        item=db.get(Incident,row.incident_id)
        if not can_access(db,user,item):continue
        if row.read_at is None:unread_count+=1
        if not unread or row.read_at is None:rows.append({'id':row.id,'read_at':row.read_at,'level':row.level,'created_at':row.created_at,'incident':incident_json(db,item)})
    rows.sort(key=lambda r:(-SEVERITIES[r['incident']['severity']],r['read_at'] is not None))
    return {'notifications':rows[offset:offset+limit],'total':len(rows),'unread_count':unread_count}


class ReadInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    read:bool=True


@router.post('/notifications/{id}/read')
def mark_read(id:int,body:ReadInput,user:User=Depends(get_current_user),db=Depends(get_db)):
    row=db.scalar(select(NotificationDelivery).where(NotificationDelivery.id==id,NotificationDelivery.user_id==user.id).with_for_update())
    if row is None or not can_access(db,user,db.get(Incident,row.incident_id)):raise HTTPException(404,'Notification not found')
    if (row.read_at is not None)!=body.read:
        history(db,db.get(Incident,row.incident_id),'notification_read' if body.read else 'notification_unread',user.id,{'notification_id':row.id})
    row.read_at=utcnow() if body.read else None
    db.commit();return {'id':row.id,'read_at':row.read_at}


@router.get('/incidents')
def incidents(status:Literal['all','open','acknowledged','resolved']='all',severity:Literal['all','low','medium','high','critical']='all',category:str=Query(default='',max_length=60),q:str=Query(default='',max_length=120),offset:int=Query(default=0,ge=0),limit:int=Query(default=30,ge=1,le=100),user:User=Depends(get_current_user),db=Depends(get_db)):
    statement=select(Incident).order_by(Incident.created_at.desc())
    if status!='all':statement=statement.where(Incident.status==status)
    if severity!='all':statement=statement.where(Incident.severity==severity)
    if category:statement=statement.where(Incident.category==category)
    rows=[item for item in db.scalars(statement).all() if can_access(db,user,item) and (not q or q.casefold() in (item.title+' '+item.detail).casefold())]
    rows.sort(key=lambda item:(item.status=='resolved',-SEVERITIES[item.severity],item.due_at))
    return {'incidents':[incident_json(db,item) for item in rows[offset:offset+limit]],'total':len(rows)}


@router.get('/incidents/{id}')
def incident_detail(id:int,user:User=Depends(get_current_user),db=Depends(get_db)):
    item=get_incident(db,user,id)
    result=incident_json(db,item,True)
    statement=select(NotificationDelivery).where(NotificationDelivery.incident_id==item.id)
    if user.role!='administrator':statement=statement.where(NotificationDelivery.user_id==user.id)
    result['deliveries']=[{'id':row.id,'user_id':row.user_id,'level':row.level,'channel':row.channel,'status':row.status,'attempts':row.attempts,'error_code':row.error_code,'read_at':row.read_at,'created_at':row.created_at} for row in db.scalars(statement).all()]
    return result


class Change(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    expected_version:int=Field(ge=1)
    action:Literal['acknowledge','resolve','assign']
    reason:str=Field(min_length=3,max_length=2000)
    assigned_user_id:int|None=Field(default=None,gt=0)
    assigned_role:Role|None=None


@router.post('/incidents/{id}/transition')
def transition(id:int,body:Change,user:User=Depends(get_current_user),db=Depends(get_db)):
    acquire_audit_lock(db)
    item=get_incident(db,user,id,True)
    if user.role=='auditor':raise HTTPException(403,'Auditors may inspect incidents but cannot change operational status')
    if item.version!=body.expected_version:raise HTTPException(409,'Incident changed; reload before submitting')
    if item.status=='resolved':raise HTTPException(409,'Incident is already resolved')
    if body.action=='resolve' and item.category=='pending_approval':raise HTTPException(409,'Use the recommendation decision workflow; pending-approval incidents close after the source decision')
    if db.execute(update(Incident).where(Incident.id==item.id,Incident.version==body.expected_version).values(version=body.expected_version)).rowcount!=1:raise HTTPException(409,'Incident changed; reload before submitting')
    before={'status':item.status,'assigned_role':item.assigned_role,'assigned_user_id':item.assigned_user_id}
    if body.action=='assign':
        if user.role!='administrator':raise HTTPException(403,'Only administrators can assign incident ownership')
        if body.assigned_role is None:raise HTTPException(422,'Select a responsible team')
        if body.assigned_role==Role.AUDITOR:raise HTTPException(422,'Auditors cannot own remediation workflows')
        if (item.category in ('unauthorized_access','policy_violation','integration_failure') or item.entity_kind=='integrations') and body.assigned_role!=Role.ADMIN:raise HTTPException(422,'This security/integration source requires administrator ownership')
        target=db.get(User,body.assigned_user_id) if body.assigned_user_id else None
        if body.assigned_user_id and (target is None or target.role!=body.assigned_role.value):raise HTTPException(422,'Responsible user must belong to the selected team')
        original=(item.assigned_role,item.assigned_user_id);item.assigned_role=body.assigned_role.value;item.assigned_user_id=body.assigned_user_id
        if target and not can_access(db,target,item):item.assigned_role,item.assigned_user_id=original;raise HTTPException(422,'Responsible user does not have access to this incident source')
        if not target and not any(u.role==item.assigned_role and can_access(db,u,item) for u in db.scalars(select(User)).all()):item.assigned_role,item.assigned_user_id=original;raise HTTPException(422,'No authorized member exists in the selected team')
        notify(db,item)
    else:
        if user.role!='administrator' and item.assigned_user_id not in (None,user.id) and not (item.escalation_level>0 and item.escalation_role==user.role):raise HTTPException(403,'This incident is assigned to another user')
        if body.assigned_role is not None or body.assigned_user_id is not None:raise HTTPException(422,'Use the assign transition to change ownership')
        if body.action=='acknowledge':
            if item.status!='open':raise HTTPException(409,'Incident is already acknowledged')
            item.status='acknowledged';item.acknowledged_at=utcnow();item.acknowledged_by=user.id
        else:item.status='resolved';item.resolved_at=utcnow();item.resolved_by=user.id;item.resolution_note=body.reason
    item.version+=1
    history(db,item,body.action,user.id,{'before':before,'after':{'status':item.status,'assigned_role':item.assigned_role,'assigned_user_id':item.assigned_user_id},'reason':body.reason})
    append_audit(db,f'notification.incident_{body.action}',user.id,{'incident_id':item.id,'before':before,'after_status':item.status,'reason':body.reason})
    db.commit();return incident_json(db,item,True)


@router.get('/notification-rules')
def rules(user:User=Depends(admin),db=Depends(get_db)):
    initialize_rules(db);db.commit()
    return {'rules':[{c.name:getattr(row,c.name) for c in row.__table__.columns} for row in db.scalars(select(NotificationRule).order_by(NotificationRule.category)).all()],'users':[{'id':u.id,'name':u.display_name,'role':u.role} for u in db.scalars(select(User)).all()],'channels':[{'name':'in_app','configured':True},{'name':'email','configured':False}]}


class RuleInput(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    expected_version:int=Field(ge=1)
    enabled:bool
    minimum_severity:Literal['low','medium','high','critical']
    assigned_role:Role
    assigned_user_id:int|None=Field(default=None,gt=0)
    escalation_role:Role
    escalation_minutes:int=Field(ge=1,le=10080)
    remediation_minutes:int=Field(ge=1,le=43200)
    quantity_threshold:float=Field(default=10000,gt=0,le=1000000000,allow_inf_nan=False)
    reason:str=Field(min_length=3,max_length=1000)


@router.put('/notification-rules/{category}')
def update_rule(category:str,body:RuleInput,user:User=Depends(admin),db=Depends(get_db)):
    if category not in CATEGORIES:raise HTTPException(404,'Notification category not found')
    acquire_audit_lock(db)
    row=db.scalar(select(NotificationRule).where(NotificationRule.category==category).with_for_update().execution_options(populate_existing=True))
    if row is None:raise HTTPException(404,'Notification rule not initialized')
    if row.version!=body.expected_version:raise HTTPException(409,'Rule changed; reload before editing')
    if db.execute(update(NotificationRule).where(NotificationRule.id==row.id,NotificationRule.version==body.expected_version).values(version=body.expected_version)).rowcount!=1:raise HTTPException(409,'Rule changed; reload before editing')
    if body.assigned_role==Role.AUDITOR or body.escalation_role==Role.AUDITOR:raise HTTPException(422,'Auditors cannot own remediation workflows')
    restricted=category in ('unauthorized_access','policy_violation','integration_failure')
    if restricted and (body.assigned_role!=Role.ADMIN or body.escalation_role!=Role.ADMIN):raise HTTPException(422,'Security and integration incidents require administrator ownership')
    target=db.get(User,body.assigned_user_id) if body.assigned_user_id else None
    if body.assigned_user_id and (target is None or target.role!=body.assigned_role.value):raise HTTPException(422,'Responsible user must belong to the selected team')
    before={c.name:getattr(row,c.name) for c in row.__table__.columns}
    for key,value in body.model_dump(exclude={'expected_version','reason'}).items():setattr(row,key,value.value if isinstance(value,Role) else value)
    row.version+=1
    after={c.name:getattr(row,c.name) for c in row.__table__.columns}
    append_audit(db,'notification.rule_changed',user.id,{'category':category,'before':before,'after':after,'reason':body.reason})
    db.commit();return after


@router.post('/notifications/reconcile')
def reconcile_now(user:User=Depends(admin),db=Depends(get_db)):
    reconcile(db)
    append_audit(db,'notification.reconciled',user.id,{'operation':'manual_deadline_and_source_check'})
    db.commit();return {'status':'checked','checked_at':utcnow()}
