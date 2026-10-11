import json
from datetime import timedelta
import httpx
import pytest
from sqlalchemy import select, func
from app.database import SessionLocal
from app.models import IntegrationConnection, IntegrationRecord, IntegrationRun, InventoryLot, Supplier, AuditEvent, ImportBatch, utcnow
from app.audit import verify_chain
from app.config import settings
from app.integrations import adapters
from app.integrations.schemas import Page, Profile
from app.security import sign_import


def create(client,headers,system='erp',mode='mock',**extra):
    response=client.post('/integrations',headers=headers,json={'name':f'{mode}-{system}','system':system,'mode':mode,'enabled':True,'reason':'Integration testing',**extra})
    assert response.status_code==201,response.text
    return response.json()


def run(client,headers,id,key='test-sync-0001',operation='sync'):
    return client.post(f'/integrations/{id}/{operation}',headers=headers,json={'idempotency_key':key,'reason':'Controlled integration test'})


def item(resource='suppliers',external_id='partner-supplier',version=1,event=None,data=None):
    return {'resource':resource,'external_id':external_id,'event_id':event or f'{external_id}-v{version}','source_version':version,'occurred_at':'2026-10-11T00:00:00Z','data':data or {'name':'Partner Components','reliability':.97,'average_lead_time':6,'defect_rate':.01,'price_variance':.03,'contact':'private-contact@example.test','compliance_status':'compliant','identity_status':'verified'}}


@pytest.fixture
def live(monkeypatch):
    def configure(system='erp',payload=None,responses=None):
        monkeypatch.setattr(settings,'integration_profiles_json',json.dumps({'test':{'system':system,'base_url':'https://partner.example','token_env':'SENTINEL_INTEGRATION_TEST_TOKEN'}}))
        monkeypatch.setenv('SENTINEL_INTEGRATION_TEST_TOKEN','unit-test-private-token')
        monkeypatch.setattr(adapters,'validate_destination',lambda url:None)
        calls=[];delays=[];responses=list(responses or [])
        def handler(request):
            calls.append(request)
            if responses:return responses.pop(0)
            return httpx.Response(200,json=payload or {'records':[item()],'next_cursor':None})
        original={'erp':adapters.ERPAdapter,'inventory':adapters.InventoryAdapter,'supplier':adapters.SupplierAdapter,'logistics':adapters.LogisticsAdapter}[system]
        monkeypatch.setitem(adapters.ADAPTERS,system,lambda profile:original(profile,transport=httpx.MockTransport(handler),sleep=delays.append))
        return calls,delays
    return configure


@pytest.mark.parametrize('role',['analyst','manager','auditor'])
def test_integration_administration_is_admin_only(client,auth,role):
    headers=auth(role)
    for path in ('/integrations','/integrations/profiles','/integrations/1/runs','/integrations/1/records'):
        assert client.get(path,headers=headers).status_code==403
    assert client.post('/integrations',headers=headers,json={'name':'Unauthorized','system':'erp','reason':'Attempted configuration'}).status_code==403
    assert run(client,headers,1).status_code==403
    assert client.post('/integrations/1/records/1/apply',headers=headers,json={'expected_source_version':1,'reason':'Attempted import'}).status_code==403


@pytest.mark.parametrize('system,count',[('erp',3),('inventory',3),('supplier',1),('logistics',2)])
def test_all_mock_adapters_are_labelled_idempotent_and_isolated(client,auth,system,count):
    admin=auth();connection=create(client,admin,system)
    result=run(client,admin,connection['id']);assert result.status_code==200,result.text
    assert result.json()['status']=='succeeded' and result.json()['accepted']==count
    duplicate=run(client,admin,connection['id']);assert duplicate.json()['duplicate_request'] is True
    replay=run(client,admin,connection['id'],'test-sync-0002');assert replay.json()['accepted']==0 and replay.json()['duplicates']==count
    inbox=client.get(f"/integrations/{connection['id']}/records",headers=admin).json()['records']
    assert all(record['provenance']=='mock' for record in inbox)
    assert client.post(f"/integrations/{connection['id']}/records/{inbox[0]['id']}/apply",headers=admin,json={'expected_source_version':1,'reason':'Try synthetic import'}).status_code==403
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Supplier.id)))==3
        assert db.scalar(select(func.count(InventoryLot.id)))==0
        assert verify_chain(db)==(True,None)


def test_live_transport_retries_and_never_exposes_credentials(client,auth,live):
    calls,delays=live(responses=[httpx.Response(503,text='private upstream failure'),httpx.Response(200,json={'records':[item()],'next_cursor':None})])
    admin=auth();connection=create(client,admin,mode='live',profile='test')
    response=run(client,admin,connection['id']);assert response.json()['status']=='succeeded' and response.json()['attempts']==2
    assert delays==[1] and len(calls)==2
    assert calls[0].headers['Authorization']=='Bearer unit-test-private-token'
    records=client.get(f"/integrations/{connection['id']}/records",headers=admin)
    assert 'private-contact' not in records.text
    for path in ('/integrations','/integrations/profiles',f"/integrations/{connection['id']}/runs",'/audit'):
        text=client.get(path,headers=admin).text
        assert 'unit-test-private-token' not in text and 'private upstream failure' not in text
    with SessionLocal() as db:
        assert 'private-contact' not in db.scalar(select(IntegrationRecord.encrypted_data))


@pytest.mark.parametrize('status,code',[(401,'authentication'),(403,'authentication'),(302,'http_status'),(404,'http_status')])
def test_permanent_errors_do_not_retry_or_claim_synchronization(client,auth,live,status,code):
    calls,delays=live(responses=[httpx.Response(status,text='secret=do-not-log')]);admin=auth();c=create(client,admin,mode='live',profile='test')
    result=run(client,admin,c['id']).json();assert result['status']=='failed' and result['error_code']==code
    assert len(calls)==1 and not delays
    assert client.get('/integrations',headers=admin).json()['connections'][0]['synced_at'] is None


def test_rate_limit_honors_cooldown_without_early_retry(client,auth,live):
    calls,delays=live(responses=[httpx.Response(429,headers={'Retry-After':'120'})]);admin=auth();c=create(client,admin,mode='live',profile='test')
    result=run(client,admin,c['id']).json();assert result['error_code']=='rate_limited' and len(calls)==1 and delays==[]
    assert run(client,admin,c['id'],'test-sync-next').status_code==429
    connection=client.get('/integrations',headers=admin).json()['connections'][0];assert connection['retry_at'] and connection['health']=='rate_limited'


def test_replay_conflict_rolls_back_entire_page(client,auth,live):
    admin=auth();live();c=create(client,admin,mode='live',profile='test');assert run(client,admin,c['id']).json()['accepted']==1
    conflicting=item(data={'name':'Tampered Components','reliability':.5,'average_lead_time':5,'defect_rate':.01,'price_variance':.03})
    live(payload={'records':[item(external_id='new-valid'),conflicting],'next_cursor':'unsafe-cursor'})
    result=run(client,admin,c['id'],'conflict-run-key').json();assert result['status']=='failed' and result['error_code']=='replay_conflict' and result['accepted']==0
    inbox=client.get(f"/integrations/{c['id']}/records",headers=admin).json();assert inbox['total']==1
    with SessionLocal() as db:assert db.get(IntegrationConnection,c['id']).cursor is None


def test_version_deduplication_and_old_versions_cannot_overwrite(client,auth,live):
    admin=auth();live(payload={'records':[item(version=2)],'next_cursor':None});c=create(client,admin,mode='live',profile='test');run(client,admin,c['id'])
    live(payload={'records':[item(version=2,event='same-version-new-id'),item(version=1)],'next_cursor':None})
    result=run(client,admin,c['id'],'older-version-run').json();assert result['duplicates']==1 and result['ignored']==1
    records=client.get(f"/integrations/{c['id']}/records",headers=admin).json()['records'];assert records[0]['source_version']==2
    live(payload={'records':[item(version=2,event='conflict-new-id',data={'name':'Changed without new version','reliability':.1,'average_lead_time':1,'defect_rate':.1,'price_variance':.1})],'next_cursor':None})
    assert run(client,admin,c['id'],'version-conflict-run').json()['error_code']=='version_conflict'


def test_live_reviewed_import_and_duplicate_apply(client,auth,live):
    admin=auth();live();c=create(client,admin,mode='live',profile='test');run(client,admin,c['id'])
    record=client.get(f"/integrations/{c['id']}/records",headers=admin).json()['records'][0]
    body={'expected_source_version':1,'reason':'Reviewed supplier onboarding'}
    imported=client.post(f"/integrations/{c['id']}/records/{record['id']}/apply",headers=admin,json=body)
    assert imported.status_code==200,imported.text
    assert client.post(f"/integrations/{c['id']}/records/{record['id']}/apply",headers=admin,json=body).json()['duplicate_request'] is True
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Supplier.id)))==4
        assert verify_chain(db)==(True,None)
        assert db.scalar(select(AuditEvent.id).where(AuditEvent.event_type=='integration.record_imported'))


def test_policy_blocks_operational_import_and_preserves_inbox(client,auth,live):
    admin=auth();live();c=create(client,admin,mode='live',profile='test');run(client,admin,c['id'])
    state=client.get('/security/policies',headers=admin).json();config=state['configuration'];config['rules']=[{'key':'block-supplier-import','operation':'supplier.update','deny_at_risk':'low'}]
    draft=client.post('/security/policies/drafts',headers=admin,json={'configuration':config,'expected_generation':state['generation'],'reason':'Restrict supplier updates'}).json()
    assert client.post(f"/security/policies/{draft['id']}/publish",headers=admin,json={'expected_generation':state['generation'],'reason':'Reviewed import policy'}).status_code==200
    record=client.get(f"/integrations/{c['id']}/records",headers=admin).json()['records'][0]
    result=client.post(f"/integrations/{c['id']}/records/{record['id']}/apply",headers=admin,json={'expected_source_version':1,'reason':'Policy denial test'})
    assert result.status_code==403,result.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Supplier.id)))==3
        assert db.get(IntegrationRecord,record['id']).applied_version is None
        assert verify_chain(db)==(True,None)


def test_stale_and_changed_source_versions_require_fresh_review(client,auth,live):
    admin=auth();live();c=create(client,admin,mode='live',profile='test');run(client,admin,c['id'])
    record=client.get(f"/integrations/{c['id']}/records",headers=admin).json()['records'][0];url=f"/integrations/{c['id']}/records/{record['id']}/apply"
    assert client.post(url,headers=admin,json={'expected_source_version':2,'reason':'Stale source review'}).status_code==409
    with SessionLocal() as db:
        db.get(IntegrationRecord,record['id']).received_at=utcnow()-timedelta(days=2);db.commit()
    assert client.get(f"/integrations/{c['id']}/records",headers=admin).json()['records'][0]['stale'] is True
    assert client.post(url,headers=admin,json={'expected_source_version':1,'reason':'Stale record review'}).status_code==409
    run(client,admin,c['id'],'refresh-confirmation')
    assert client.get(f"/integrations/{c['id']}/records",headers=admin).json()['records'][0]['stale'] is False


def test_disabled_busy_and_stale_configuration_are_guarded(client,auth):
    admin=auth();c=create(client,admin,enabled=False)
    assert run(client,admin,c['id']).status_code==409
    assert client.post(f"/integrations/{c['id']}/state",headers=admin,json={'enabled':True,'expected_version':2,'reason':'Stale state change'}).status_code==409
    assert client.post(f"/integrations/{c['id']}/state",headers=admin,json={'enabled':True,'expected_version':1,'reason':'Enable test connection'}).status_code==200
    with SessionLocal() as db:
        db.get(IntegrationConnection,c['id']).lease_until=utcnow()+timedelta(seconds=60);db.commit()
    assert run(client,admin,c['id']).status_code==409
    assert client.post(f"/integrations/{c['id']}/state",headers=admin,json={'enabled':False,'expected_version':2,'reason':'Pause busy connection'}).status_code==409


@pytest.mark.parametrize('payload',[{'records':[item(data={'name':'Invalid','reliability':2})],'next_cursor':None},{'records':[item(resource='inventory',data={'sku':'X','lot_number':'L','quantity':1,'location':''})],'next_cursor':None},{'records':[],'next_cursor':None,'secret':'unexpected'}])
def test_invalid_partner_contract_is_rejected_without_inbox_writes(client,auth,live,payload):
    admin=auth();live(payload=payload);c=create(client,admin,mode='live',profile='test')
    result=run(client,admin,c['id']).json();assert result['status']=='failed' and result['error_code']=='validation'
    assert client.get(f"/integrations/{c['id']}/records",headers=admin).json()['total']==0


def test_missing_credentials_and_production_mock_safeguard(client,auth,live,monkeypatch):
    admin=auth();live();c=create(client,admin,mode='live',profile='test');monkeypatch.delenv('SENTINEL_INTEGRATION_TEST_TOKEN')
    assert run(client,admin,c['id']).json()['error_code']=='credentials'
    monkeypatch.setattr(settings,'environment','production')
    response=client.post('/integrations',headers=admin,json={'name':'Production mock','system':'erp','mode':'mock','reason':'Attempt synthetic connection'})
    assert response.status_code==403


def test_private_destinations_and_redirects_are_rejected(monkeypatch):
    monkeypatch.setattr(adapters.socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(adapters.AdapterFailure,match='not public'):adapters.validate_destination('https://partner.example')
    monkeypatch.setattr(settings,'integration_profiles_json',json.dumps({'bad':{'system':'erp','base_url':'http://partner.example','token_env':'SENTINEL_INTEGRATION_TEST_TOKEN'}}))
    with pytest.raises(adapters.AdapterFailure):adapters.profiles()


def test_inventory_import_links_warehouse_and_applies_movement_once(client,auth,live):
    admin=auth();payload={'records':[item('warehouses','wh',data={'code':'EXT-WH','name':'External warehouse','location':'Dock'}),item('inventory','lot',data={'sku':'SKU-001','lot_number':'EXT-LOT','quantity':20,'location':'Dock','warehouse_external_id':'wh'}),item('stock-movements','movement',data={'lot_external_id':'lot','movement_type':'issue','quantity':3,'reason':'Partner issue'})]}
    live('inventory',payload);c=create(client,admin,system='inventory',mode='live',profile='test');assert run(client,admin,c['id']).json()['accepted']==3
    records={r['external_id']:r for r in client.get(f"/integrations/{c['id']}/records",headers=admin).json()['records']}
    def apply(key,**extra):return client.post(f"/integrations/{c['id']}/records/{records[key]['id']}/apply",headers=admin,json={'expected_source_version':1,'reason':'Review partner inventory',**extra})
    assert apply('lot').status_code==422
    wh=apply('wh').json()['entity_id'];lot_result=apply('lot');assert lot_result.status_code==200,lot_result.text;lot=lot_result.json()['entity_id']
    assert apply('movement',expected_entity_version=99).status_code==409
    result=apply('movement',expected_entity_version=1);assert result.status_code==200,result.text
    assert apply('movement',expected_entity_version=1).json()['duplicate_request']
    with SessionLocal() as db:
        from app.models import EntityGovernance,StockMovement
        assert db.get(InventoryLot,lot).quantity==17
        assert db.scalar(select(EntityGovernance).where(EntityGovernance.kind=='inventory',EntityGovernance.entity_id==lot)).warehouse_id==wh
        assert db.scalar(select(func.count(StockMovement.id)).where(StockMovement.lot_id==lot))==1
        assert verify_chain(db)==(True,None)


def test_logistics_import_keeps_workflow_status_and_appends_tracking_once(client,auth,live):
    admin=auth();payload={'records':[item('shipments','shipment',data={'shipment_number':'EXT-SHIP','carrier':'Partner','tracking_number':'EXT-T','reported_status':'delivered','estimated_arrival':'2026-10-12T00:00:00Z'}),item('tracking-events','tracking',data={'shipment_external_id':'shipment','status':'delivered','location':'Destination','notes':'Carrier reported arrival'})]}
    live('logistics',payload);c=create(client,admin,system='logistics',mode='live',profile='test');assert run(client,admin,c['id']).json()['accepted']==2
    records={r['external_id']:r for r in client.get(f"/integrations/{c['id']}/records",headers=admin).json()['records']}
    def apply(key,**extra):return client.post(f"/integrations/{c['id']}/records/{records[key]['id']}/apply",headers=admin,json={'expected_source_version':1,'reason':'Review partner logistics',**extra})
    shipment=apply('shipment').json()['entity_id'];result=apply('tracking',expected_entity_version=1);assert result.status_code==200,result.text
    assert apply('tracking',expected_entity_version=1).json()['duplicate_request']
    with SessionLocal() as db:
        from app.models import Shipment,TrackingEvent
        assert db.get(Shipment,shipment).status=='planned'
        assert db.scalar(select(func.count(TrackingEvent.id)).where(TrackingEvent.shipment_id==shipment))==1
        assert verify_chain(db)==(True,None)


def test_noncompliant_update_checks_incoming_risk_before_mutation(client,auth,live):
    admin=auth();source=item();source['data']['compliance_status']='non_compliant';live(payload={'records':[source]});c=create(client,admin,mode='live',profile='test');run(client,admin,c['id'])
    state=client.get('/security/policies',headers=admin).json();config=state['configuration'];config['rules']=[{'key':'block-critical-supplier','operation':'supplier.update','deny_at_risk':'critical'}]
    draft=client.post('/security/policies/drafts',headers=admin,json={'configuration':config,'expected_generation':state['generation'],'reason':'Reject critical supplier writes'}).json();assert client.post(f"/security/policies/{draft['id']}/publish",headers=admin,json={'expected_generation':state['generation'],'reason':'Review critical risk gate'}).status_code==200
    record=client.get(f"/integrations/{c['id']}/records",headers=admin).json()['records'][0]
    response=client.post(f"/integrations/{c['id']}/records/{record['id']}/apply",headers=admin,json={'expected_source_version':1,'target_entity_id':1,'expected_entity_version':1,'reason':'Review noncompliance evidence'})
    assert response.status_code==403,response.text
    with SessionLocal() as db:
        assert db.get(Supplier,1).name!='Partner Components'
        assert db.get(IntegrationRecord,record['id']).applied_version is None
        assert verify_chain(db)==(True,None)
