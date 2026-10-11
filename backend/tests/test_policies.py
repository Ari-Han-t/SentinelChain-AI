import copy
import json
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from app.database import SessionLocal
from app.models import PolicyRevision, PolicyState, AuditEvent, InventoryLot
from app.audit import verify_chain


def current(client, headers):
    response=client.get('/security/policies',headers=headers)
    assert response.status_code==200,response.text
    return response.json()


def draft(client, headers, config, generation=1):
    return client.post('/security/policies/drafts',headers=headers,json={'configuration':config,'expected_generation':generation,'reason':'Security control review'})


def publish(client, headers, config):
    state=current(client,headers);response=draft(client,headers,config,state['generation'])
    assert response.status_code==201,response.text
    result=client.post(f"/security/policies/{response.json()['id']}/publish",headers=headers,json={'expected_generation':state['generation'],'reason':'Reviewed security controls'})
    assert result.status_code==200,result.text
    return response.json()['id']


def rule(**patch):
    return {'key':'sensitive-change','operation':'inventory.change','priority':100,'active':True,'minimum_clearance':1,'deny_at_risk':'none','max_quantity_delta':None,'effective_from':None,'effective_until':None,**patch}


@pytest.mark.parametrize('role',['analyst','manager','auditor'])
def test_policy_administration_cannot_be_escalated(client,auth,role):
    admin=auth();headers=auth(role);config=current(client,admin)['configuration']
    assert client.get('/security/policies',headers=headers).status_code==403
    assert draft(client,headers,config).status_code==403
    for action in ('publish','revert'):
        assert client.post(f'/security/policies/1/{action}',headers=headers,json={'expected_generation':1,'reason':'Attempted change'}).status_code==403
    assert client.post('/security/policies/users/2/role',headers=headers,json={'role':'administrator','expected_role':'inventory_analyst','reason':'Escalation attempt'}).status_code==403


def test_draft_publish_direct_api_and_revert(client,auth):
    admin=auth();analyst=auth('analyst');config=copy.deepcopy(current(client,admin)['configuration'])
    config['role_permissions']['inventory_analyst'].remove('forecast.manage')
    response=draft(client,admin,config);assert response.status_code==201
    assert 'forecast.manage' in client.get('/auth/permissions',headers=analyst).json()['permissions']
    rid=response.json()['id'];body={'expected_generation':1,'reason':'Approval after review'}
    assert client.post(f'/security/policies/{rid}/publish',headers=admin,json=body).status_code==200
    assert 'forecast.manage' not in client.get('/auth/permissions',headers=analyst).json()['permissions']
    assert client.post('/forecasts/SKU-001/train',headers=analyst).status_code==403
    assert client.post(f'/security/policies/{rid}/publish',headers=admin,json=body).status_code==409
    restored=client.post('/security/policies/1/revert',headers=admin,json={'expected_generation':2,'reason':'Rollback reviewed restrictions'})
    assert restored.status_code==200
    assert restored.json()['active_revision_id'] not in (1,rid)
    assert 'forecast.manage' in client.get('/auth/permissions',headers=analyst).json()['permissions']
    with SessionLocal() as db:
        assert verify_chain(db)==(True,None)
        event=db.scalar(select(AuditEvent).where(AuditEvent.event_type=='policy.published'));payload=json.loads(event.payload_json)
        assert payload['before']!=payload['after'] and payload['reason'] and event.actor_id
        assert db.get(PolicyRevision,1).published_by is None


@pytest.mark.parametrize('mutation',['escalate','admin-lockout','unknown','missing','bad-clearance','duplicate-rule','bad-date','wrong-operation'])
def test_invalid_policy_never_saved(client,auth,mutation):
    admin=auth();config=current(client,admin)['configuration']
    if mutation=='escalate':config['role_permissions']['auditor'].append('entity.manage')
    elif mutation=='admin-lockout':config['role_permissions']['administrator']=[]
    elif mutation=='unknown':config['untrusted_ai_override']=True
    elif mutation=='missing':del config['entity_clearance']['inventory']
    elif mutation=='bad-clearance':config['operation_clearance']['forecast.modify']=0
    elif mutation=='duplicate-rule':config['rules']=[rule(),rule()]
    elif mutation=='bad-date':config['rules']=[rule(effective_from='2026-01-01T00:00:00')]
    else:config['rules']=[rule(operation='supplier.update',max_quantity_delta=3)]
    assert draft(client,admin,config).status_code==422
    assert len(current(client,admin)['revisions'])==1


def test_stale_draft_and_stale_restoration_rejected(client,auth):
    admin=auth();config=current(client,admin)['configuration'];first=draft(client,admin,config).json()['id']
    publish(client,admin,config)
    assert client.post(f'/security/policies/{first}/publish',headers=admin,json={'expected_generation':2,'reason':'Stale policy draft'}).status_code==409
    assert client.post('/security/policies/1/revert',headers=admin,json={'expected_generation':1,'reason':'Stale rollback'}).status_code==409
    assert current(client,admin)['generation']==2


@pytest.mark.parametrize('mode',['clearance','quantity','risk'])
def test_inventory_policy_blocks_legacy_and_management_writes_atomically(client,auth,mode):
    admin=auth();analyst=auth('analyst')
    created=client.post('/inventory/lots',headers=admin,json={'sku':'SKU-001','lot_number':'POLICY-LOT','quantity':10,'location':'Warehouse'})
    assert created.status_code==200,created.text
    lot=created.json();config=current(client,admin)['configuration']
    if mode=='clearance':config['operation_clearance']['inventory.change']=4
    elif mode=='quantity':config['rules']=[rule(max_quantity_delta=2)]
    else:config['rules']=[rule(deny_at_risk='low')]
    publish(client,admin,config)
    response=client.post('/inventory/movements',headers=analyst if mode=='clearance' else admin,json={'lot_id':lot['id'],'movement_type':'receipt','quantity':3,'reason':'Controlled movement'})
    assert response.status_code==403,response.text
    if mode!='clearance':
        item=client.get(f"/entities/inventory/{lot['id']}",headers=admin).json()
        response=client.put(f"/entities/inventory/{lot['id']}",headers=admin,json={'data':{'sku':'SKU-001','lot_number':'POLICY-LOT','quantity':13,'location':'Warehouse'},'governance':item['governance'],'expected_version':item['version'],'reason':'Direct management adjustment'})
        assert response.status_code==403,response.text
    with SessionLocal() as db:
        assert db.get(InventoryLot,lot['id']).quantity==10
        assert verify_chain(db)==(True,None)


def test_entity_clearance_floor_enforced_in_legacy_reads(client,auth):
    admin=auth();config=current(client,admin)['configuration'];config['entity_clearance']['suppliers']=4
    publish(client,admin,config)
    assert client.get('/suppliers',headers=auth('analyst')).json()==[]
    assert client.get('/entities/suppliers/1',headers=auth('auditor')).status_code==403
    assert client.get('/entities/suppliers/1',headers=admin).status_code==200


@pytest.mark.parametrize('active,offset,blocked',[(False,0,False),(True,1,False),(True,-1,True)])
def test_rules_respect_activation_and_effective_dates(client,auth,active,offset,blocked):
    admin=auth();config=current(client,admin)['configuration'];start=datetime.now(timezone.utc)+timedelta(days=offset)
    config['rules']=[rule(operation='forecast.modify',active=active,deny_at_risk='low',effective_from=start.isoformat())]
    publish(client,admin,config)
    response=client.post('/forecasts/SKU-001/train',headers=auth('analyst'))
    assert response.status_code==(403 if blocked else 200),response.text


@pytest.mark.parametrize('invalid',['missing','corrupt','digest','status'])
def test_missing_or_invalid_policy_fails_securely(client,auth,invalid):
    headers=auth()
    with SessionLocal() as db:
        state=db.get(PolicyState,1);revision=db.get(PolicyRevision,state.active_revision_id)
        if invalid=='missing':db.delete(state)
        elif invalid=='corrupt':revision.configuration_json='{}'
        elif invalid=='digest':revision.digest='0'*64
        else:revision.status='draft'
        db.commit()
    assert client.get('/dashboard',headers=headers).status_code==503
    assert client.post('/inventory/lots',headers=headers,json={'sku':'SKU-001','lot_number':'FAIL','quantity':1,'location':'Test'}).status_code==503


def test_role_assignment_uses_database_role_for_existing_token_and_protects_self(client,auth):
    admin=auth();analyst=auth('analyst');users=current(client,admin)['users'];target=next(u for u in users if u['role']=='inventory_analyst');root=next(u for u in users if u['role']=='administrator')
    response=client.post(f"/security/policies/users/{target['id']}/role",headers=admin,json={'role':'auditor','expected_role':'inventory_analyst','reason':'Role reassignment reviewed'})
    assert response.status_code==200
    assert client.get('/auth/permissions',headers=analyst).json()['role']=='auditor'
    assert client.post('/forecasts/SKU-001/train',headers=analyst).status_code==403
    assert client.post(f"/security/policies/users/{root['id']}/role",headers=admin,json={'role':'auditor','expected_role':'administrator','reason':'Self demotion'}).status_code==409


def test_approval_threshold_preserves_pending_and_rejection(client,auth):
    admin=auth();manager=auth('manager')
    assert client.post('/forecasts/SKU-001/train',headers=admin).status_code==200
    r=client.post('/recommendations/generate/SKU-001',headers=admin)
    assert r.status_code==200,r.text
    rid=r.json()['id'];config=current(client,admin)['configuration'];config['approval_quantity_threshold']=0
    publish(client,admin,config)
    assert client.post(f'/recommendations/{rid}/decision',headers=manager,json={'decision':'approved','expected_status':'pending','note':'Manager review'}).status_code==403
    assert client.get('/recommendations',headers=admin).json()[0]['status']=='pending'
    assert client.post(f'/recommendations/{rid}/decision',headers=manager,json={'decision':'rejected','expected_status':'pending','note':'Needs administrator review'}).status_code==200


def test_supplier_rule_denial_leaves_data_unchanged(client,auth):
    admin=auth();old=client.get('/entities/suppliers/1',headers=admin).json();config=current(client,admin)['configuration']
    config['rules']=[rule(operation='supplier.update',deny_at_risk='low')];publish(client,admin,config)
    fields={k:v for k,v in old['data'].items() if k in ('name','reliability','average_lead_time','defect_rate','price_variance')};fields['name']='Blocked supplier rename'
    response=client.put('/entities/suppliers/1',headers=admin,json={'data':fields,'governance':old['governance'],'expected_version':old['version'],'reason':'Synthetic policy check'})
    assert response.status_code==403,response.text
    assert client.get('/entities/suppliers/1',headers=admin).json()['data']['name']==old['data']['name']
    assert client.post('/entities/suppliers/1/state',headers=admin,json={'active':False,'expected_version':old['version'],'reason':'Blocked retirement'}).status_code==403
    assert client.get('/entities/suppliers/1',headers=admin).json()['active'] is True


@pytest.mark.parametrize('role,permission,url', [('auditor','audit.read','/audit'),('manager','action.decide','/actions/999/decision'),('analyst','inventory.manage','/inventory/lots')])
def test_revoked_permissions_are_enforced_on_direct_requests(client,auth,role,permission,url):
    admin=auth();user=auth(role);config=current(client,admin)['configuration'];full_role=client.get('/auth/permissions',headers=user).json()['role'];config['role_permissions'][full_role].remove(permission);publish(client,admin,config)
    if url=='/audit':response=client.get(url,headers=user)
    elif url.startswith('/actions'):response=client.post(url,headers=user,json={'decision':'approved','expected_status':'pending','note':'Check policy'})
    else:response=client.post(url,headers=user,json={'sku':'SKU-001','lot_number':'REVOKED','quantity':5,'location':'Test'})
    assert response.status_code==403,response.text


def test_expired_rule_does_not_block_current_requests(client,auth):
    admin=auth();config=current(client,admin)['configuration'];config['rules']=[rule(operation='forecast.modify',deny_at_risk='low',effective_until=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat())];publish(client,admin,config)
    assert client.post('/forecasts/SKU-001/train',headers=auth('analyst')).status_code==200
