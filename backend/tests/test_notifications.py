from datetime import timedelta
import pytest
from sqlalchemy import select,func
from app.database import SessionLocal
from app.models import Incident,NotificationDelivery,IncidentOccurrence,NotificationRule,User,Role,IntegrationConnection,IntegrationRun,ActionProposal,OperationalTask,EntityGovernance,InventoryLot,utcnow
from app.notifications.service import emit,reconcile
from app.notifications.delivery import CHANNELS,DeliveryFailure,deliver
from app.audit import append_audit,verify_chain


def create_incident(category='supplier_risk',severity='critical',identity='test',**extra):
    with SessionLocal() as db:
        item=emit(db,category,severity,f'test-{identity}',identity,detail='Explicit test source signal',**extra);db.commit();return item.id


def test_notifications_are_deduplicated_and_read_is_personal(client,auth):
    admin=auth();id=create_incident()
    with SessionLocal() as db:
        emit(db,'supplier_risk','critical','test-test','test',detail='Same event');db.commit()
        assert db.scalar(select(func.count(Incident.id)))==1;assert db.get(Incident,id).occurrence_count==1
        assert db.scalar(select(func.count(NotificationDelivery.id)))==1
    data=client.get('/notifications',headers=admin).json();row=data['notifications'][0];assert data['unread_count']==1
    assert client.post(f"/notifications/{row['id']}/read",headers=admin,json={'read':True}).status_code==200
    assert client.get('/notifications?unread=true',headers=admin).json()['total']==0
    assert client.post(f"/notifications/{row['id']}/read",headers=auth('analyst'),json={'read':True}).status_code==404
    assert client.post(f"/notifications/{row['id']}/read",headers=admin,json={'read':False}).status_code==200


def test_acknowledged_critical_incident_still_escalates_once(client,auth):
    admin=auth();id=create_incident();current=client.get(f'/incidents/{id}',headers=admin).json()
    result=client.post(f'/incidents/{id}/transition',headers=admin,json={'action':'acknowledge','expected_version':current['version'],'reason':'Investigating source'});assert result.status_code==200,result.text
    with SessionLocal() as db:item=db.get(Incident,id);item.escalation_at=utcnow()-timedelta(minutes=1);db.commit();reconcile(db);reconcile(db)
    current=client.get(f'/incidents/{id}',headers=admin).json();assert current['status']=='acknowledged';assert current['escalation_level']==1;assert len([e for e in current['history'] if e['event_type']=='escalated'])==1
    with SessionLocal() as db:assert len(db.scalars(select(NotificationDelivery).where(NotificationDelivery.incident_id==id)).all())==2;assert verify_chain(db)==(True,None)


def test_resolution_and_recurrence_preserve_history(client,auth):
    admin=auth();id=create_incident();current=client.get(f'/incidents/{id}',headers=admin).json()
    assert client.post(f'/incidents/{id}/transition',headers=admin,json={'action':'resolve','expected_version':99,'reason':'Stale conflict'}).status_code==409
    result=client.post(f'/incidents/{id}/transition',headers=admin,json={'action':'resolve','expected_version':current['version'],'reason':'Reviewed mitigation completed'});assert result.status_code==200,result.text
    with SessionLocal() as db:
        emit(db,'supplier_risk','critical','new-occurrence','test',detail='New source event');db.commit();item=db.get(Incident,id);assert item.status=='resolved';assert item.resolution_note=='Reviewed mitigation completed';new=db.scalar(select(Incident).where(Incident.id!=id));assert new.status=='open';assert new.occurrence_count==1
    result=client.get(f'/incidents/{id}',headers=admin).json();assert [e['event_type'] for e in result['history']]==['created','resolve']


def test_roles_clearance_and_assignment_never_grant_access(client,auth):
    admin=auth();id=create_incident(entity_kind='products',entity_id=1)
    with SessionLocal() as db:db.add(EntityGovernance(kind='products',entity_id=1,minimum_clearance=4));db.commit()
    current=client.get(f'/incidents/{id}',headers=admin).json()
    assert client.get(f'/incidents/{id}',headers=auth('manager')).status_code==404
    assert client.post(f'/incidents/{id}/transition',headers=admin,json={'action':'assign','expected_version':current['version'],'assigned_role':'procurement_manager','assigned_user_id':3,'reason':'Attempt hidden-source assignment'}).status_code==422
    assert client.post(f'/incidents/{id}/transition',headers=auth('auditor'),json={'action':'acknowledge','expected_version':current['version'],'reason':'Read-only auditor'}).status_code in (403,404)


@pytest.mark.parametrize('role',['analyst','manager','auditor'])
def test_rules_and_manual_scheduler_are_administrator_only(client,auth,role):
    headers=auth(role)
    assert client.get('/notification-rules',headers=headers).status_code==403
    assert client.post('/notifications/reconcile',headers=headers).status_code==403
    assert client.put('/notification-rules/supplier_risk',headers=headers,json={'expected_version':1,'enabled':False,'minimum_severity':'high','assigned_role':'administrator','escalation_role':'administrator','escalation_minutes':60,'remediation_minutes':240,'reason':'Unauthorized rule update'}).status_code==403


def test_rule_version_threshold_and_disabled_rule(client,auth):
    admin=auth();rules=client.get('/notification-rules',headers=admin).json()['rules'];rule=next(r for r in rules if r['category']=='supplier_risk');body={key:value for key,value in rule.items() if key not in ('id','category','version')};body.update(expected_version=rule['version'],enabled=False,reason='Pause test delivery rule')
    result=client.put('/notification-rules/supplier_risk',headers=admin,json=body);assert result.status_code==200,result.text
    assert client.put('/notification-rules/supplier_risk',headers=admin,json=body).status_code==409
    with SessionLocal() as db:assert emit(db,'supplier_risk','critical','disabled-event','disabled') is None;db.commit();assert verify_chain(db)==(True,None)


def test_auth_policy_and_failed_integration_events_are_real_safe_sources(client,auth):
    admin=auth();assert client.post('/auth/login',json={'email':'absent@example.test','password':'do-not-log-password'}).status_code==401
    assert client.post('/notifications/reconcile',headers=auth('analyst')).status_code==403
    c=client.post('/integrations',headers=admin,json={'name':'Mock failure','system':'erp','mode':'mock','enabled':True,'mock_scenario':'invalid','reason':'Test integration failure'}).json()
    assert client.post(f"/integrations/{c['id']}/sync",headers=admin,json={'idempotency_key':'notification-failure','reason':'Read failed run'}).json()['status']=='failed'
    with SessionLocal() as db:reconcile(db);reconcile(db);incidents=db.scalars(select(Incident)).all();assert any(i.category=='unauthorized_access' for i in incidents);failure=next(i for i in incidents if i.category=='integration_failure');assert failure.occurrence_count==1;assert 'Synthetic mock' in failure.detail
    text=client.get('/incidents',headers=admin).text;assert 'do-not-log-password' not in text;assert 'absent@example.test' not in text


def test_overdue_action_and_pending_approval_auto_closure(client,auth):
    admin=auth()
    with SessionLocal() as db:
        action=ActionProposal(node_id=2,title='Overdue fixture',reason='Deadline test source',owner_role='inventory_analyst');db.add(action);db.flush();action.due_at=utcnow()-timedelta(hours=1);id=action.id;db.commit();reconcile(db)
    assert any(i['category']=='overdue_remediation' for i in client.get('/incidents',headers=admin).json()['incidents'])
    assert client.post(f'/actions/{id}/decision',headers=admin,json={'decision':'rejected','note':'Reviewed overdue action'}).status_code==200
    with SessionLocal() as db:reconcile(db);rows=db.scalars(select(Incident).where(Incident.category=='pending_approval',Incident.entity_id==id,Incident.entity_kind=='stage-actions')).all();assert rows and all(i.status=='resolved' for i in rows)


def test_delivery_retry_is_bounded_and_uses_stable_idempotency_key(client,auth,monkeypatch):
    auth();calls=[]
    class Temporary:
        def deliver(self,**kwargs):calls.append(kwargs['idempotency_key']);raise DeliveryFailure('temporary',True)
    monkeypatch.setitem(CHANNELS,'in_app',Temporary());id=create_incident()
    with SessionLocal() as db:
        row=db.scalar(select(NotificationDelivery).where(NotificationDelivery.incident_id==id));assert row.status=='pending';assert row.attempts==1
        deliver(row);assert row.attempts==1
        for _ in range(2):row.next_attempt_at=utcnow()-timedelta(seconds=1);deliver(row)
        assert row.status=='failed';assert row.attempts==3;assert len(set(calls))==1;db.commit()


def test_concurrent_denied_requests_preserve_audit_chain_and_incident_dedup(client,auth):
    from concurrent.futures import ThreadPoolExecutor
    auth()
    def denied(_):
        with SessionLocal() as db:append_audit(db,'auth.denied',None,{'outcome':'denied','reason':'invalid_authentication'});db.commit()
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(denied,range(12)))
    with SessionLocal() as db:
        assert verify_chain(db)==(True,None)
        rows=db.scalars(select(Incident).where(Incident.category=='unauthorized_access')).all();assert len(rows)==1;assert rows[0].occurrence_count==12
        assert len(db.scalars(select(NotificationDelivery).where(NotificationDelivery.incident_id==rows[0].id)).all())==1


def test_inventory_notification_threshold_uses_actual_movement(client,auth):
    admin=auth()
    with SessionLocal() as db:
        rule=db.scalar(select(NotificationRule).where(NotificationRule.category=='inventory_change'));rule.quantity_threshold=10
        lot=InventoryLot(sku='SKU-001',lot_number='Threshold-fixture',quantity=20,location='Test');db.add(lot);db.commit();id=lot.id
    result=client.post('/inventory/movements',headers=admin,json={'lot_id':id,'movement_type':'receipt','quantity':11,'reason':'Review threshold movement'});assert result.status_code==200,result.text
    with SessionLocal() as db:assert db.scalar(select(Incident).where(Incident.category=='inventory_change',Incident.entity_id==id)) is not None


@pytest.mark.parametrize('attack_type,category',[('demand_poisoning','demand_poisoning'),('inventory_manipulation','inventory_change'),('supplier_spoofing','supplier_spoofing')])
def test_simulation_alert_and_audit_are_one_notification_source(client,auth,attack_type,category):
    admin=auth();response=client.post('/demo/attacks',headers=admin,json={'attack_type':attack_type,'sku':'SKU-001'});assert response.status_code==200
    with SessionLocal() as db:
        reconcile(db);reconcile(db)
        rows=db.scalars(select(Incident).where(Incident.category==category)).all();assert len(rows)==1;assert rows[0].occurrence_count==1;assert 'synthetic attack' in rows[0].detail
        assert db.scalar(select(func.count(IncidentOccurrence.id)).where(IncidentOccurrence.incident_id==rows[0].id))==1


def test_pending_approval_cannot_be_resolved_without_source_decision(client,auth):
    admin=auth();id=create_incident(category='pending_approval',severity='medium')
    assert client.post(f'/incidents/{id}/transition',headers=admin,json={'action':'resolve','expected_version':1,'reason':'Skip pending approval'}).status_code==409
