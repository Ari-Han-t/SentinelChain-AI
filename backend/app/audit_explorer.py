import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .database import get_db
from .models import AuditEvent, User, Role, Product, Recommendation, ActionProposal, Incident, SecuritySimulation, IntegrationConnection
from .security import require_roles
from .entities import accessible
from .audit import verify_chain
from .observability import sanitize
router=APIRouter(prefix='/security',tags=['Security visibility'])

def describe(db,event):
    p=json.loads(event.payload_json); ctx=p.get('_context',{})
    entity=None
    if p.get('kind') and p.get('entity_id'): entity={'kind':p['kind'],'id':p['entity_id']}
    for key,kind in [('node_id','stages'),('lot_id','inventory'),('supplier_id','suppliers'),('product_id','products'),('shipment_id','shipments'),('purchase_order_id','purchase-orders')]:
        if p.get(key): entity={'kind':kind,'id':p[key]};break
    if p.get('sku'):
        product=db.scalar(select(Product).where(Product.sku==p['sku']))
        if product:entity={'kind':'products','id':product.id}
    for key,model,kind,attr in [('recommendation_id',Recommendation,'products','product_id'),('action_id',ActionProposal,'stages','node_id')]:
        if p.get(key) and (row:=db.get(model,p[key])):entity={'kind':kind,'id':getattr(row,attr)}
    if p.get('incident_id') and (row:=db.get(Incident,p['incident_id'])) and row.entity_kind:entity={'kind':row.entity_kind,'id':row.entity_id}
    denied='denied' in event.event_type or event.event_type=='auth.failed' or p.get('outcome')=='denied'
    outcome=p.get('outcome') or p.get('status') or ('denied' if denied else 'recorded')
    return {'id':event.id,'sequence':event.sequence,'event_type':event.event_type,'actor_id':event.actor_id,'actor_name':db.get(User,event.actor_id).display_name if event.actor_id and db.get(User,event.actor_id) else 'Service / anonymous','identity_type':'user' if event.actor_id else ctx.get('identity','legacy unknown'),'entity':entity,'created_at':event.created_at,'authorization_decision':'denied' if denied else 'not captured' if not ctx else p.get('authorization_decision','Not separately captured'),'policy_revision_id':ctx.get('policy_revision_id') or p.get('revision_id'),'request_id':ctx.get('request_id'),'outcome':outcome,'reason':p.get('reason') or p.get('error_code') or p.get('note'),'severity':p.get('severity') or ('high' if denied or outcome=='failed' else 'info'),'related':{k:p[k] for k in ('incident_id','simulation_id','recommendation_id','action_id','run_id') if k in p},'payload':sanitize(p),'event_hash':event.event_hash,'previous_hash':event.previous_hash,'metadata_state':'captured' if ctx else 'legacy_not_captured'}

def visible(db,user,row):
    entity=row['entity']
    # Integrations retain their administrator-only source scope.
    if (row['event_type'].startswith('integration.') or entity and entity['kind']=='integrations') and user.role!='administrator':return False
    return not entity or entity['kind'] not in ('products','suppliers','warehouses','inventory','shipments','purchase-orders') or accessible(db,user,entity['kind'],entity['id'])

@router.get('/audit')
def security_audit_explore(user:User=Depends(require_roles(Role.ADMIN,Role.AUDITOR)),db:Session=Depends(get_db),action:str=Query('',max_length=100),actor_id:int|None=None,entity:str=Query('',max_length=100),severity:str=Query('',max_length=20),outcome:str=Query('',max_length=40),since:datetime|None=None,until:datetime|None=None,offset:int=Query(0,ge=0),limit:int=Query(30,ge=1,le=100)):
    if any(v and v.tzinfo is None for v in (since,until)):raise HTTPException(422,'Date filters require a timezone')
    if since and until and since>until:raise HTTPException(422,'Start date must precede end date')
    stmt=select(AuditEvent).order_by(AuditEvent.sequence.desc())
    if action:stmt=stmt.where(AuditEvent.event_type.contains(action,autoescape=True))
    if actor_id is not None:stmt=stmt.where(AuditEvent.actor_id==actor_id)
    if since:stmt=stmt.where(AuditEvent.created_at>=since)
    if until:stmt=stmt.where(AuditEvent.created_at<=until)
    rows=[]
    for event in db.scalars(stmt):
        row=describe(db,event)
        if visible(db,user,row) and (not entity or entity.lower() in json.dumps(row['entity']).lower()) and (not severity or row['severity']==severity) and (not outcome or row['outcome']==outcome):rows.append(row)
    valid,broken=verify_chain(db)
    return {'records':rows[offset:offset+limit],'total':len(rows),'valid':valid,'broken_at':broken,'users':[{'id':u.id,'name':u.display_name} for u in db.scalars(select(User).order_by(User.id))]}

@router.get('/overview')
def security_operations_overview(user:User=Depends(require_roles(Role.ADMIN,Role.AUDITOR)),db:Session=Depends(get_db)):
    from .notifications.service import can_access
    incidents=[i for i in db.scalars(select(Incident).where(Incident.status!='resolved')) if can_access(db,user,i)]
    valid,broken=verify_chain(db)
    return {'audit_integrity':{'valid':valid,'broken_at':broken},'unresolved_incidents':[{'id':i.id,'title':i.title,'severity':i.severity,'status':i.status,'owner':i.assigned_role,'due_at':i.due_at,'escalated':bool(i.escalation_level)} for i in sorted(incidents,key=lambda i:(0 if i.severity=='critical' else 1,i.due_at))[:10]],'unresolved_total':len(incidents),'recent_simulations':[{'id':s.id,'scenario':s.scenario,'status':json.loads(s.report_json)['status'],'created_at':s.created_at} for s in db.scalars(select(SecuritySimulation).order_by(SecuritySimulation.id.desc()).limit(5))],'integration_health':[{'id':c.id,'name':c.name,'mode':c.mode,'enabled':c.enabled,'synced_at':c.synced_at,'health':c.health} for c in db.scalars(select(IntegrationConnection).limit(20))] if user.role=='administrator' else [],'environment':settings_environment()}
def settings_environment():
    from .config import settings
    return {'name':settings.environment,'simulations_enabled':settings.demo_mode and settings.environment.lower()!='production','demo_data':settings.seed_demo_data}
