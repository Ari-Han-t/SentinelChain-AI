"""Run actual application routes against a disposable database, without lifespan/network adapters."""
import json
from typing import Literal
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from .database import Base, get_db
from .models import User, Role, Product, Supplier, SaleRecord, AuditEvent, SecuritySimulation, PolicyState, PolicyRevision, EntityGovernance
from .security import require_roles, create_access_token, sign_import
from .audit import append_audit, verify_chain
from .config import settings
from .policies import active_policy, initialize_policy
from .observability import sanitize

SCENARIOS = ('demand_poisoning','inventory_manipulation','supplier_spoofing','privilege_escalation','clearance_bypass','unauthorized_policy_change','evidence_tampering','integration_replay')
class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')
    scenario: Literal['demand_poisoning','inventory_manipulation','supplier_spoofing','privilege_escalation','clearance_bypass','unauthorized_policy_change','evidence_tampering','integration_replay']
    reason: str = Field(min_length=3,max_length=1000)
router=APIRouter(prefix='/security/simulations', tags=['Isolated simulations'])

def execute(scenario, configuration):
    from .main import app
    from .seed import seed_database
    sandbox_engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    factory=sessionmaker(bind=sandbox_engine,autoflush=False,expire_on_commit=False)
    Base.metadata.create_all(sandbox_engine)
    seed_database(factory,initialize=False)
    with factory() as db:
        initialize_policy(db)
        state=db.get(PolicyState,1); revision=db.get(PolicyRevision,state.active_revision_id)
        revision.configuration_json=json.dumps(configuration.model_dump(mode='json'),sort_keys=True,separators=(',',':'))
        import hashlib
        revision.digest=hashlib.sha256(revision.configuration_json.encode()).hexdigest()
        db.commit()
        users={u.role:u for u in db.scalars(select(User))}
        baseline={'stock':db.get(Product,1).current_stock,'suppliers':db.scalar(select(func.count(Supplier.id))),'sales':db.scalar(select(func.count(SaleRecord.id))),'policy_generation':state.generation}
    sandbox=FastAPI()
    allowed={'/imports','/inventory/movements','/entities/{kind}','/entities/{kind}/{entity_id}','/security/policies/drafts','/integrations','/integrations/{id}/sync'}
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path in allowed:
            sandbox.add_api_route(route.path, route.endpoint, methods=list(route.methods), dependencies=route.dependencies, response_model=route.response_model, status_code=route.status_code, name=route.name)
    def private_db():
        with factory() as db: yield db
    sandbox.dependency_overrides[get_db]=private_db
    steps=[]; expected='blocked'; detected=False; blocked=False
    try:
        with TestClient(sandbox,raise_server_exceptions=False) as client:
            def request(method,path,role='administrator',**kw):
                headers={'Authorization':'Bearer '+create_access_token(users[role])}
                response=client.request(method,path,headers=headers,**kw)
                steps.append({'method':method,'path':path,'persona':role,'http_status':response.status_code})
                return response
            if scenario=='demand_poisoning':
                original='sku,date,quantity\nSKU-001,2026-01-01,20\n'
                r=request('POST','/imports',json={'dataset_name':'isolated-invalid-signature','csv_content':original.replace(',20',',12000'),'signature':sign_import(original.encode())})
                detected=blocked=r.status_code in (400,403,422)
            elif scenario=='inventory_manipulation':
                r=request('POST','/inventory/movements',json={'lot_id':1,'movement_type':'adjustment','quantity':-500,'reason':'Isolated impossible adjustment'})
                detected=blocked=r.status_code==422
            elif scenario=='supplier_spoofing':
                r=request('POST','/entities/suppliers',role='inventory_analyst',json={'name':'Forged supplier','reliability':1,'average_lead_time':1,'defect_rate':0,'price_variance':0,'contact':'fixture@example.test'})
                detected=blocked=r.status_code==403
            elif scenario=='privilege_escalation':
                import jwt
                token=jwt.decode(create_access_token(users['inventory_analyst']),settings.jwt_secret,algorithms=['HS256'])
                token['role']='administrator'
                forged=jwt.encode(token,settings.jwt_secret,algorithm='HS256')
                r=client.post('/security/policies/drafts',headers={'Authorization':'Bearer '+forged},json={})
                steps.append({'method':'POST','path':'/security/policies/drafts','persona':'analyst with forged role claim','http_status':r.status_code})
                detected=blocked=r.status_code==403
            elif scenario=='clearance_bypass':
                with factory() as db:
                    row=db.scalar(select(EntityGovernance).where(EntityGovernance.kind=='products',EntityGovernance.entity_id==1))
                    if row is None: row=EntityGovernance(kind='products',entity_id=1);db.add(row)
                    row.minimum_clearance=4;db.commit()
                r=request('GET','/entities/products/1',role='inventory_analyst')
                detected=blocked=r.status_code==403
            elif scenario=='unauthorized_policy_change':
                r=request('POST','/security/policies/drafts',role='auditor',json={})
                detected=blocked=r.status_code==403
            elif scenario=='evidence_tampering':
                expected='detected'
                with factory() as db:
                    event=db.scalar(select(AuditEvent).order_by(AuditEvent.sequence))
                    event.payload_json='{"tampered_evidence":true}';db.commit()
                    valid,broken=verify_chain(db)
                    detected=not valid
                    steps.append({'action':'Modify disposable ledger evidence','integrity_valid':valid,'broken_at':broken})
            else:
                expected='deduplicated'
                c=request('POST','/integrations',json={'name':'Isolated ERP','system':'erp','mode':'mock','enabled':True,'reason':'Sandbox replay test'})
                if c.status_code==201:
                    id=c.json()['id']; first=request('POST',f'/integrations/{id}/sync',json={'idempotency_key':'sandbox-first','reason':'First mock synchronization'})
                    replay=request('POST',f'/integrations/{id}/sync',json={'idempotency_key':'sandbox-replay','reason':'Replay mock synchronization'})
                    duplicated=request('POST',f'/integrations/{id}/sync',json={'idempotency_key':'sandbox-replay','reason':'Repeat request key'})
                    detected=blocked=first.status_code==replay.status_code==duplicated.status_code==200 and replay.json()['accepted']==0 and replay.json()['duplicates']>0 and duplicated.json()['duplicate_request']
                    steps.append({'accepted':first.json().get('accepted'),'replayed_accepted':replay.json().get('accepted'),'duplicates':replay.json().get('duplicates')})
        with factory() as db:
            final={'stock':db.get(Product,1).current_stock,'suppliers':db.scalar(select(func.count(Supplier.id))),'sales':db.scalar(select(func.count(SaleRecord.id))),'policy_generation':db.get(PolicyState,1).generation}
            events=[{'sequence':x.sequence,'event_type':x.event_type,'payload':sanitize(json.loads(x.payload_json))} for x in db.scalars(select(AuditEvent).order_by(AuditEvent.sequence))]
        unchanged=baseline==final
        return {'scenario':scenario,'isolation':'disposable in-memory SQLite; synthetic fixtures; no live adapters','affected_entities':['synthetic product SKU-001','synthetic users/policy/integration as applicable'],'initial_conditions':baseline,'final_conditions':final,'operational_state_unchanged':unchanged,'simulated_actions':steps,'policy_configuration_digest':__import__('hashlib').sha256(json.dumps(configuration.model_dump(mode='json'),sort_keys=True).encode()).hexdigest(),'policies_evaluated': {'demand_poisoning':['Manifest HMAC verification'], 'inventory_manipulation':['Positive bounded movement quantity input validation'], 'supplier_spoofing':['Immutable role ceiling for entity.manage'], 'privilege_escalation':['Database role lookup; administrator-only policy configuration'], 'clearance_bypass':['Published entity clearance and fixture minimum clearance 4'], 'unauthorized_policy_change':['Administrator-only policy draft guard'], 'evidence_tampering':['Audit sequence, previous hash and canonical payload hash'], 'integration_replay':['Run idempotency key; source event/version deduplication']}[scenario], 'expected_outcome':expected,'actual_outcome':expected if detected else 'unexpected_result','detected':bool(detected),'blocked':bool(blocked),'status':'passed' if detected and unchanged else 'failed','audit_events':events}
    finally: sandbox_engine.dispose()

@router.post('',status_code=201)
def run_simulation(body:Input,user:User=Depends(require_roles(Role.ADMIN)),db:Session=Depends(get_db)):
    if not settings.demo_mode or settings.environment.lower()=='production': raise HTTPException(404,'Simulations are disabled in this environment')
    config,state=active_policy(db)
    report=execute(body.scenario,config)
    item=SecuritySimulation(scenario=body.scenario,actor_id=user.id,policy_revision_id=state.active_revision_id,report_json=json.dumps(report))
    db.add(item);db.flush()
    event=append_audit(db,'simulation.completed',user.id,{'simulation_id':item.id,'scenario':body.scenario,'status':report['status'],'reason':body.reason,'isolation':report['isolation']})
    item.audit_id=event.id;db.commit()
    return record(item)

def record(item):
    return {'id':item.id,'scenario':item.scenario,'actor_id':item.actor_id,'policy_revision_id':item.policy_revision_id,'audit_id':item.audit_id,'created_at':item.created_at,'report':json.loads(item.report_json)}
@router.get('')
def simulation_history(user:User=Depends(require_roles(Role.ADMIN,Role.AUDITOR)),db:Session=Depends(get_db),offset:int=Query(0,ge=0),limit:int=Query(30,ge=1,le=100)):
    return {'records':[record(x) for x in db.scalars(select(SecuritySimulation).order_by(SecuritySimulation.id.desc()).offset(offset).limit(limit))],'total':db.scalar(select(func.count(SecuritySimulation.id))),'enabled':settings.demo_mode and settings.environment.lower()!='production','scenarios':list(SCENARIOS)}
