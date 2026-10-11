"""Evidence snapshots and a shared human-decision history; never grants authority."""
import json
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select,update
from .database import get_db
from .models import (Recommendation,ActionProposal,RecommendationSnapshot,RecommendationProgress,
    RecommendationHistoryEvent,StageRiskAssessment,Product,Forecast,SaleRecord,GuidanceRun,EvidenceRecord,SupplyChainNode,User,Role,utcnow)
from .security import get_current_user,require_roles
from .entities import accessible,guard,entity_risk
from .policies import enforce
from .audit import append_audit,acquire_audit_lock

router=APIRouter(prefix='/recommendation-history',tags=['recommendation-history'])
MODELS={'stock':Recommendation,'stage':ActionProposal}


def source(db,kind,id,user=None,write=False):
    if kind not in MODELS:raise HTTPException(404,'Recommendation kind not found')
    item=db.get(MODELS[kind],id)
    if item is None:raise HTTPException(404,'Recommendation not found')
    if user:
        if kind=='stock':guard(db,user,'products',item.product_id,write)
        elif user.role==Role.ANALYST.value and item.owner_role!=user.role:raise HTTPException(403,'Stage recommendation belongs to another operating team')
    return item


def explanation(db,kind,item):
    """Only actual captured inputs; legacy reconstruction is explicitly not historical evidence."""
    if kind=='stock':
        product=db.get(Product,item.product_id);forecast=db.get(Forecast,item.forecast_id)
        data={'forecast_id':item.forecast_id,'daily_demand':forecast.daily_demand if forecast else None,'forecast_model':forecast.model_name if forecast else None,'forecast_created_at':str(forecast.created_at) if forecast else None,'reorder_point':item.reorder_point,'safety_stock':item.safety_stock,'eoq':item.eoq,'recommended_quantity':item.recommended_quantity,'supplier_risk':item.supplier_risk}
        evidence=[{'kind':'forecast','id':item.forecast_id,'summary':'Stored demand forecast and inventory policy calculations','data':data}]
        return {'summary':f'Review replenishment for {product.sku if product else "missing product"}.','affected':{'kind':'products','id':item.product_id,'name':product.name if product else 'Unavailable'},'category':'availability','severity':'critical' if item.supplier_risk>=80 else 'high' if item.supplier_risk>=60 else 'medium' if item.recommended_quantity else 'low','evidence':evidence,'reasoning':'Reorder point combines forecast demand across lead time with safety stock. Economic order quantity balances stored order and holding costs. Recommended quantity is a planning suggestion requiring human review.','consequences':['Insufficient stock may interrupt fulfilment.','Excess replenishment may increase holding costs.','Unverified demand or supplier inputs can distort purchasing decisions.'],'mitigation':['Validate forecast input provenance and current stock.','Confirm lead time, supplier suitability and budget.','Use the existing human approval workflow before implementation.'],'confidence':None,'confidence_basis':'No calibrated probability or outcome model is available. Forecast error metrics are model-validation observations, not confidence in this action.','missing_information':['No supplier-to-product contractual relationship is modeled. The aggregate supplier risk does not identify a selected supplier.','Actual post-implementation outcomes must be supplied by an authorized user.'],'risk_values':{'supplier_risk':item.supplier_risk,'recommended_quantity':item.recommended_quantity}}
    node=db.get(SupplyChainNode,item.node_id);run=db.get(GuidanceRun,item.guidance_run_id) if item.guidance_run_id else None
    ids=json.loads(run.evidence_ids_json) if run else []
    evidence=[];missing=[]
    for id in ids:
        row=db.get(EvidenceRecord,id)
        if row and row.node_id==item.node_id:evidence.append({'kind':'evidence','id':id,'summary':row.summary,'source':row.source_type,'status':row.status,'occurred_at':str(row.occurred_at)})
        else:missing.append(f'Cited evidence {id} is unavailable or belongs to another stage.')
    if not evidence:missing.append('No valid cited evidence was available. The reported stage state requires verification.')
    missing.append('Model and heuristic scores are not calibrated probabilities. Operational outcomes have not been independently verified.')
    return {'summary':item.title,'affected':{'kind':'stages','id':item.node_id,'name':node.name if node else 'Unavailable'},'category':node.stage_type if node else 'operational','severity':item.urgency if item.urgency in ('high','critical') else 'medium','evidence':evidence,'reasoning':item.reason,'consequences':[item.expected_impact or 'Operational impact was not supplied.','Acting on unverified or disputed source evidence can propagate incorrect decisions.'],'mitigation':['Verify cited source records and reconcile disputes.',item.title,'Record a human decision, implementation status and actual outcome.'],'confidence':None,'confidence_basis':'Provider score withheld: no calibrated action confidence is available.','missing_information':missing,'provider':run.provider if run else 'not_recorded','risk_values':{'stage_status':node.status if node else 'unknown','urgency':item.urgency}}


def capture(db,kind,item):
    if db.scalar(select(RecommendationSnapshot.id).where(RecommendationSnapshot.kind==kind,RecommendationSnapshot.source_id==item.id)):return
    payload=explanation(db,kind,item)
    if kind=='stock':
        product=db.get(Product,item.product_id)
        count=len(db.scalars(select(SaleRecord.id).where(SaleRecord.product_id==item.product_id)).all())
        payload['evidence'].append({'kind':'product','id':item.product_id,'summary':'Generation-time stock and cost inputs','data':{'current_stock':product.current_stock,'lead_time_days':product.lead_time_days,'unit_cost':product.unit_cost,'order_cost':product.order_cost,'holding_cost_rate':product.holding_cost_rate,'available_sales_count':count}})
    payload['snapshot_state']='captured_at_generation'
    db.add(RecommendationSnapshot(kind=kind,source_id=item.id,explanation_json=json.dumps(payload,default=str)))
    db.flush()


def project_audit(db,event,payload):
    kind=None;id=None
    if event.event_type=='recommendation.generated':
        item=db.get(Recommendation,payload['recommendation_id']);capture(db,'stock',item);kind='stock';id=item.id
    elif event.event_type=='guidance.generated':
        run_id=payload.get('run_id')
        if run_id:
            run=db.get(GuidanceRun,run_id);node=db.get(SupplyChainNode,run.node_id)
            db.add(StageRiskAssessment(node_id=node.id,run_id=run.id,assessment_json=json.dumps({'stage_status':node.status,'severity':{'healthy':'low','at_risk':'high','critical':'critical','stale':'medium'}.get(node.status,'medium'),'evidence_ids':json.loads(run.evidence_ids_json),'provider':run.provider,'summary':run.status_summary})))
            for item in db.scalars(select(ActionProposal).where(ActionProposal.guidance_run_id==run_id)).all():capture(db,'stage',item)
        return
    elif event.event_type.startswith('recommendation.') and 'recommendation_id' in payload:kind='stock';id=payload['recommendation_id']
    elif event.event_type.startswith('action.') and 'action_id' in payload:kind='stage';id=payload['action_id']
    if kind and id:
        progress=db.scalar(select(RecommendationProgress).where(RecommendationProgress.kind==kind,RecommendationProgress.source_id==id).with_for_update())
        if progress:progress.version+=1;progress.updated_at=utcnow()
        else:db.add(RecommendationProgress(kind=kind,source_id=id))
        from .models import PolicyState
        policy=db.get(PolicyState,1)
        detail=dict(payload)
        if policy:detail['policy_revision_id']=policy.active_revision_id;detail['policy_generation']=policy.generation
        db.add(RecommendationHistoryEvent(kind=kind,source_id=id,event_type=event.event_type,actor_id=event.actor_id,audit_id=event.id,detail_json=json.dumps(detail,default=str),created_at=event.created_at));db.flush()


def record_json(db,kind,item,detail=False):
    snapshot=db.scalar(select(RecommendationSnapshot).where(RecommendationSnapshot.kind==kind,RecommendationSnapshot.source_id==item.id))
    payload=json.loads(snapshot.explanation_json) if snapshot else explanation(db,kind,item)
    if not snapshot:
        payload['snapshot_state']='legacy_not_captured'
        payload['missing_information'].append('Generation-time inputs were not captured for this legacy record. Displayed explanation uses stored outputs and currently available related records, not a historical input snapshot.')
    progress=db.scalar(select(RecommendationProgress).where(RecommendationProgress.kind==kind,RecommendationProgress.source_id==item.id))
    actor=db.get(User,item.decided_by) if item.decided_by else None
    result={'kind':kind,'source_id':item.id,'created_at':item.created_at,'status':item.status,'decided_by':{'id':actor.id,'name':actor.display_name} if actor else None,'decision_note':item.decision_note,'explanation':payload,'version':progress.version if progress else 1,'implementation_status':progress.implementation_status if progress else 'not_started','outcome':progress.outcome if progress else '', 'feedback':progress.feedback if progress else ''}
    if detail:
        events=db.scalars(select(RecommendationHistoryEvent).where(RecommendationHistoryEvent.kind==kind,RecommendationHistoryEvent.source_id==item.id).order_by(RecommendationHistoryEvent.id)).all()
        result['history']=[{'id':e.id,'event_type':e.event_type,'actor_id':e.actor_id,'actor_name':db.get(User,e.actor_id).display_name if e.actor_id and db.get(User,e.actor_id) else 'System','created_at':e.created_at,'detail':json.loads(e.detail_json),'audit_id':e.audit_id} for e in events]
        affected=payload['affected'];comparisons=[]
        for prior in db.scalars(select(RecommendationSnapshot).where(RecommendationSnapshot.kind==kind,RecommendationSnapshot.source_id!=item.id).order_by(RecommendationSnapshot.created_at.desc())).all():
            old=json.loads(prior.explanation_json)
            if old['affected']['id']==affected['id']:comparisons.append({'source_id':prior.source_id,'created_at':prior.created_at,'severity':old['severity'],'risk_values':old.get('risk_values',{})})
            if len(comparisons)==10:break
        if kind=='stage':
            comparisons=[{'run_id':row.run_id,'created_at':row.created_at,**json.loads(row.assessment_json)} for row in db.scalars(select(StageRiskAssessment).where(StageRiskAssessment.node_id==item.node_id).order_by(StageRiskAssessment.created_at.desc()).limit(10)).all()]
        result['risk_history']=comparisons
    return result


@router.get('')
def list_history(kind:Literal['all','stock','stage']='all',status:str='',severity:str='',q:str=Query(default='',max_length=120),offset:int=Query(default=0,ge=0),limit:int=Query(default=30,ge=1,le=100),user:User=Depends(get_current_user),db=Depends(get_db)):
    rows=[]
    for k,model in MODELS.items():
        if kind not in ('all',k):continue
        for item in db.scalars(select(model).order_by(model.created_at.desc())).all():
            if k=='stock' and not accessible(db,user,'products',item.product_id):continue
            if k=='stage' and user.role==Role.ANALYST.value and item.owner_role!=user.role:continue
            row=record_json(db,k,item)
            if status and row['status']!=status or severity and row['explanation']['severity']!=severity:continue
            if q and q.casefold() not in (row['explanation']['summary']+' '+row['explanation']['affected']['name']).casefold():continue
            rows.append(row)
    rows.sort(key=lambda r:r['created_at'],reverse=True)
    return {'records':rows[offset:offset+limit],'total':len(rows)}


@router.get('/{kind}/{source_id}')
def history_detail(kind:str,source_id:int,user:User=Depends(get_current_user),db=Depends(get_db)):
    return record_json(db,kind,source(db,kind,source_id,user),True)


class Decision(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    decision:Literal['approved','rejected','dismissed','deferred']
    expected_status:Literal['pending','deferred']
    note:str=Field(min_length=3,max_length=1000)


@router.post('/{kind}/{source_id}/decision')
def history_decision(kind:str,source_id:int,body:Decision,user:User=Depends(require_roles(Role.ADMIN,Role.MANAGER)),db=Depends(get_db)):
    item=source(db,kind,source_id,user,True)
    if body.decision=='deferred' and body.expected_status=='deferred':raise HTTPException(409,'Recommendation is already deferred')
    if body.decision=='approved':enforce(db,user,'approval.decide',risk=entity_risk(db,'products',item.product_id) if kind=='stock' else item.urgency if item.urgency in ('high','critical') else 'low',recommendation=item if kind=='stock' else None)
    result=db.execute(update(MODELS[kind]).where(MODELS[kind].id==source_id,MODELS[kind].status==body.expected_status).values(status=body.decision,decided_by=user.id,decision_note=body.note))
    if result.rowcount!=1:raise HTTPException(409,'Recommendation changed; reload before deciding')
    append_audit(db,f'{"recommendation" if kind=="stock" else "action"}.{body.decision}',user.id,{f'{"recommendation" if kind=="stock" else "action"}_id':source_id,'previous_status':body.expected_status,'status':body.decision,'note':body.note})
    db.commit();db.expire_all();return record_json(db,kind,source(db,kind,source_id),True)


class Feedback(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    expected_version:int=Field(ge=1)
    implementation_status:Literal['not_started','in_progress','completed','failed','cancelled']
    outcome:str=Field(default='',max_length=2000)
    feedback:str=Field(default='',max_length=2000)
    reason:str=Field(min_length=3,max_length=1000)


@router.post('/{kind}/{source_id}/feedback')
def history_feedback(kind:str,source_id:int,body:Feedback,user:User=Depends(require_roles(Role.ADMIN,Role.MANAGER)),db=Depends(get_db)):
    acquire_audit_lock(db)
    item=source(db,kind,source_id,user,True)
    if item.status!='approved' and body.implementation_status!='not_started':raise HTTPException(409,'Only approved recommendations may be reported as implemented')
    if body.implementation_status in ('completed','failed','cancelled') and len(body.outcome)<3:raise HTTPException(422,'Record an outcome for a final implementation state')
    progress=db.scalar(select(RecommendationProgress).where(RecommendationProgress.kind==kind,RecommendationProgress.source_id==source_id).with_for_update())
    if progress is None:progress=RecommendationProgress(kind=kind,source_id=source_id,version=1);db.add(progress);db.flush()
    if progress.version!=body.expected_version:raise HTTPException(409,'Progress changed; reload before submitting')
    if db.execute(update(RecommendationProgress).where(RecommendationProgress.id==progress.id,RecommendationProgress.version==body.expected_version).values(version=body.expected_version)).rowcount!=1:raise HTTPException(409,'Progress changed; reload before submitting')
    if progress.implementation_status in ('completed','cancelled') and body.implementation_status!=progress.implementation_status:raise HTTPException(409,'A completed/cancelled implementation cannot be reopened')
    before={'implementation_status':progress.implementation_status,'outcome':progress.outcome,'feedback':progress.feedback}
    progress.implementation_status=body.implementation_status;progress.outcome=body.outcome;progress.feedback=body.feedback
    append_audit(db,f'{"recommendation" if kind=="stock" else "action"}.feedback_recorded',user.id,{f'{"recommendation" if kind=="stock" else "action"}_id':source_id,'before':before,'after':body.model_dump(exclude={'expected_version'}),'note':body.reason})
    db.commit();return record_json(db,kind,item,True)
