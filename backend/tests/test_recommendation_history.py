import json
import pytest
from sqlalchemy import select
from app.database import SessionLocal
from app.models import Recommendation,RecommendationSnapshot,RecommendationProgress,ActionProposal,Product,EntityGovernance,utcnow
from app.audit import verify_chain,append_audit


def stock(client,headers):
    # Existing forecast model uses real synthetic seed sales, not fabricated explanation rows.
    assert client.post('/forecasts/SKU-001/train',headers=headers).status_code==200
    response=client.post('/recommendations/generate/SKU-001',headers=headers)
    assert response.status_code==200,response.text
    return response.json()['id']


def test_generation_captures_inputs_and_history_does_not_rewrite_them(client,auth):
    admin=auth();id=stock(client,admin)
    before=client.get(f'/recommendation-history/stock/{id}',headers=admin).json()
    assert before['explanation']['snapshot_state']=='captured_at_generation'
    assert before['explanation']['confidence'] is None
    with SessionLocal() as db:
        product=db.get(Product,1);product.current_stock=999;db.commit()
    after=client.get(f'/recommendation-history/stock/{id}',headers=admin).json()
    assert before['explanation']==after['explanation']
    assert after['history'][0]['event_type']=='recommendation.generated'


@pytest.mark.parametrize('decision',['deferred','dismissed','rejected','approved'])
def test_decision_history_and_stale_replay(client,auth,decision):
    admin=auth();id=stock(client,admin)
    result=client.post(f'/recommendation-history/stock/{id}/decision',headers=admin,json={'decision':decision,'expected_status':'pending','note':'Reviewed source evidence'})
    assert result.status_code==200,result.text
    body=result.json();assert body['status']==decision;assert body['decided_by']['name']=='Ari Admin';assert body['history'][-1]['detail']['policy_revision_id']
    assert client.post(f'/recommendation-history/stock/{id}/decision',headers=admin,json={'decision':'approved','expected_status':'pending','note':'Duplicate stale decision'}).status_code==409
    if decision=='deferred':assert client.post(f'/recommendation-history/stock/{id}/decision',headers=admin,json={'decision':'approved','expected_status':'deferred','note':'Additional evidence reviewed'}).status_code==200
    with SessionLocal() as db:assert verify_chain(db)==(True,None)


def test_feedback_requires_approval_version_and_final_outcome(client,auth):
    admin=auth();id=stock(client,admin);url=f'/recommendation-history/stock/{id}'
    current=client.get(url,headers=admin).json()
    report={'expected_version':current['version'],'implementation_status':'completed','outcome':'Verified manually','feedback':'User report','reason':'Record operational outcome'}
    assert client.post(url+'/feedback',headers=admin,json=report).status_code==409
    approved=client.post(url+'/decision',headers=admin,json={'decision':'approved','expected_status':'pending','note':'Reviewed available facts'}).json()
    report['expected_version']=approved['version'];assert client.post(url+'/feedback',headers=admin,json={**report,'outcome':''}).status_code==422
    result=client.post(url+'/feedback',headers=admin,json=report);assert result.status_code==200,result.text
    assert result.json()['implementation_status']=='completed'
    assert client.post(url+'/feedback',headers=admin,json=report).status_code==409
    with SessionLocal() as db:assert verify_chain(db)==(True,None)


@pytest.mark.parametrize('role',['analyst','auditor'])
def test_direct_history_writes_require_authority(client,auth,role):
    admin=auth();id=stock(client,admin);headers=auth(role)
    assert client.post(f'/recommendation-history/stock/{id}/decision',headers=headers,json={'decision':'approved','expected_status':'pending','note':'Unauthorized request'}).status_code==403
    assert client.post(f'/recommendation-history/stock/{id}/feedback',headers=headers,json={'expected_version':1,'implementation_status':'not_started','reason':'Unauthorized report'}).status_code==403


def test_current_clearance_and_published_permissions_apply_to_history(client,auth):
    admin=auth();id=stock(client,admin);manager=auth('manager')
    with SessionLocal() as db:db.add(EntityGovernance(kind='products',entity_id=1,minimum_clearance=4));db.commit()
    assert client.get(f'/recommendation-history/stock/{id}',headers=manager).status_code==403
    assert all(row['source_id']!=id or row['kind']!='stock' for row in client.get('/recommendation-history',headers=manager).json()['records'])
    state=client.get('/security/policies',headers=admin).json();configuration=state['configuration'];configuration['role_permissions']['procurement_manager'].remove('action.decide')
    draft=client.post('/security/policies/drafts',headers=admin,json={'configuration':configuration,'expected_generation':state['generation'],'reason':'Restrict decisions'}).json();client.post(f"/security/policies/{draft['id']}/publish",headers=admin,json={'expected_generation':state['generation'],'reason':'Reviewed restriction'})
    assert client.post(f'/recommendation-history/stock/{id}/decision',headers=manager,json={'decision':'rejected','expected_status':'pending','note':'Restricted decision'}).status_code==403


def test_legacy_history_is_honest_and_stage_assessments_are_preserved(client,auth):
    admin=auth()
    with SessionLocal() as db:
        legacy=ActionProposal(node_id=2,title='Legacy fixture recommendation',reason='Stored fixture without original snapshot',owner_role='inventory_analyst');db.add(legacy);db.commit();id=legacy.id
    result=client.get(f'/recommendation-history/stage/{id}',headers=admin).json();assert result['explanation']['snapshot_state']=='legacy_not_captured'
    assert client.post('/nodes/2/guidance/refresh',headers=admin).status_code==200
    assert client.post('/nodes/2/guidance/refresh',headers=admin).status_code==200
    with SessionLocal() as db:
        action=db.scalar(select(ActionProposal).where(ActionProposal.node_id==2));id=action.id
    data=client.get(f'/recommendation-history/stage/{id}',headers=admin).json()
    assert len(data['risk_history'])>=2
    assert data['explanation']['confidence'] is None


def test_history_approval_respects_published_quantity_threshold(client,auth):
    admin=auth()
    with SessionLocal() as db:db.get(Product,1).current_stock=0;db.commit()
    id=stock(client,admin);state=client.get('/security/policies',headers=admin).json();configuration=state['configuration'];configuration['approval_quantity_threshold']=1
    draft=client.post('/security/policies/drafts',headers=admin,json={'configuration':configuration,'expected_generation':state['generation'],'reason':'Administrator review for replenishment'}).json();client.post(f"/security/policies/{draft['id']}/publish",headers=admin,json={'expected_generation':state['generation'],'reason':'Reviewed threshold'})
    response=client.post(f'/recommendation-history/stock/{id}/decision',headers=auth('manager'),json={'decision':'approved','expected_status':'pending','note':'Try restricted approval'})
    assert response.status_code==403,response.text
    with SessionLocal() as db:assert db.get(Recommendation,id).status=='pending';assert verify_chain(db)==(True,None)
