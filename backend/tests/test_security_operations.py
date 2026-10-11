import json
import pytest
from sqlalchemy import select, func
from app.database import SessionLocal
from app.models import Product, Supplier, SecuritySimulation, AuditEvent
from app.audit import verify_chain
from app.config import settings
from app.simulations import SCENARIOS

@pytest.mark.parametrize('scenario',SCENARIOS)
def test_isolated_simulation_evaluates_real_routes_and_preserves_operations(client,auth,scenario):
    headers=auth()
    with SessionLocal() as db:
        before=[(p.id,p.current_stock) for p in db.scalars(select(Product))]
        suppliers=db.scalar(select(func.count(Supplier.id)))
        audit_before=db.scalar(select(func.count(AuditEvent.id)))
    result=client.post('/security/simulations',headers=headers,json={'scenario':scenario,'reason':'Controlled regression scenario'})
    assert result.status_code==201,result.text
    report=result.json()['report']
    assert report['status']=='passed',report
    assert report['detected'] and report['operational_state_unchanged']
    assert 'Bearer' not in result.text and 'demo1234' not in result.text
    with SessionLocal() as db:
        assert before==[(p.id,p.current_stock) for p in db.scalars(select(Product))]
        assert suppliers==db.scalar(select(func.count(Supplier.id)))
        assert verify_chain(db)==(True,None)
        assert db.scalar(select(func.count(AuditEvent.id)))==audit_before+1

@pytest.mark.parametrize('role',['analyst','manager','auditor'])
def test_simulation_write_boundary(client,auth,role):
    assert client.post('/security/simulations',headers=auth(role),json={'scenario':'clearance_bypass','reason':'Unauthorized attempt'}).status_code==403

def test_production_simulations_disabled_even_if_demo_flag_misconfigured(client,auth,monkeypatch):
    headers=auth();monkeypatch.setattr(settings,'environment','production')
    assert client.post('/security/simulations',headers=headers,json={'scenario':'clearance_bypass','reason':'Production forbidden'}).status_code==404
    assert client.post('/demo/attacks',headers=headers,json={'attack_type':'demand_poisoning'}).status_code==404

def test_audit_search_correlation_dates_redaction_and_read_only(client,auth):
    headers=auth()
    res=client.get('/security/audit?action=auth.login',headers=headers)
    assert res.status_code==200
    event=res.json()['records'][0]
    assert event['request_id'] and event['policy_revision_id']
    assert '@sentinelchain' not in res.text
    assert client.get('/security/audit?since=2026-01-01',headers=headers).status_code==422
    assert client.get('/security/audit?severity=high&outcome=denied',headers=auth('auditor')).status_code==200
    assert client.get('/security/audit',headers=auth('analyst')).status_code==403
    assert client.delete('/security/audit/1',headers=headers).status_code in (404,405)

def test_security_overview_and_response_headers(client,auth):
    response=client.get('/security/overview',headers=auth())
    assert response.status_code==200,response.text
    assert response.json()['audit_integrity']['valid']
    assert response.headers.get('X-Content-Type-Options')=='nosniff'
    assert response.headers.get('X-Request-ID')

def test_audit_entity_clearance_and_related_source_scope(client,auth):
    from app.models import EntityGovernance
    from app.audit import append_audit
    headers=auth()
    with SessionLocal() as db:
        row=db.scalar(select(EntityGovernance).where(EntityGovernance.kind=='products',EntityGovernance.entity_id==1))
        if row is None:row=EntityGovernance(kind='products',entity_id=1);db.add(row)
        row.minimum_clearance=4
        append_audit(db,'forecast.trained',1,{'sku':'SKU-001','forecast_id':100})
        db.commit()
    assert client.get('/security/audit?action=forecast.trained',headers=headers).json()['total']==1
    assert client.get('/security/audit?action=forecast.trained',headers=auth('auditor')).json()['total']==0

def test_ready_fails_safely_when_policy_is_missing(client):
    from app.models import PolicyState
    with SessionLocal() as db:
        db.delete(db.get(PolicyState,1));db.commit()
    response=client.get('/ready')
    assert response.status_code==503 and 'Database or policy' in response.json()['detail']

def test_postgres_timestamp_normalization():
    from datetime import datetime, timezone, timedelta
    from app.models import utc_naive
    assert utc_naive(datetime(2026,1,1,5,30,tzinfo=timezone(timedelta(hours=5,minutes=30))))==datetime(2026,1,1)
