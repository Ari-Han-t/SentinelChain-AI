from ..models import utc_naive
import hashlib
import json
from datetime import timedelta
from sqlalchemy import select
from ..models import (NotificationRule,Incident,IncidentOccurrence,IncidentHistory,NotificationDelivery,User,Role,
    Recommendation,ActionProposal,Supplier,InventoryLot,Alert,IntegrationRun,IntegrationConnection,OperationalTask,Product,utcnow)
from ..entities import accessible
from ..policies import effective_permissions
from .delivery import deliver

CATEGORIES={'supplier_risk':'Critical supplier risk','inventory_change':'Suspicious inventory change','demand_poisoning':'Potential demand poisoning','supplier_spoofing':'Supplier identity spoofing','unauthorized_access':'Unauthorized access attempt','policy_violation':'Policy violation','pending_approval':'Pending approval','integration_failure':'Failed external integration','overdue_remediation':'Overdue remediation task'}
SEVERITIES={'low':0,'medium':1,'high':2,'critical':3}


def initialize_rules(db):
    for category in CATEGORIES:
        if not db.scalar(select(NotificationRule.id).where(NotificationRule.category==category).with_for_update()):
            role='procurement_manager' if category=='pending_approval' else 'inventory_analyst' if category in ('inventory_change','demand_poisoning') else 'administrator'
            db.add(NotificationRule(category=category,assigned_role=role,minimum_severity='medium'))
    db.flush()


def can_access(db,user,item):
    # Assignment never grants entity clearance or security administration privileges.
    if item.category in ('unauthorized_access','policy_violation'):
        return user.role=='administrator' or user.role=='auditor' and 'audit.read' in effective_permissions(db,user.role)
    if item.category=='integration_failure' or item.entity_kind=='integrations':return user.role=='administrator'
    if item.entity_kind in ('products','suppliers','inventory','warehouses','shipments','purchase-orders'):
        if not accessible(db,user,item.entity_kind,item.entity_id):return False
    if item.entity_kind=='stage-actions':
        action=db.get(ActionProposal,item.entity_id)
        if action and user.role=='inventory_analyst' and action.owner_role!=user.role:return False
    return user.role in ('administrator','auditor') or item.assigned_user_id==user.id or item.assigned_user_id is None and item.assigned_role==user.role or item.escalation_level>0 and item.escalation_role==user.role


def history(db,item,event,actor=None,detail=None):
    db.add(IncidentHistory(incident_id=item.id,event_type=event,actor_id=actor,detail_json=json.dumps(detail or {},default=str)));db.flush()


def notify(db,item,level=None):
    level=item.escalation_level if level is None else level
    target_role=item.escalation_role if level else item.assigned_role
    for user in db.scalars(select(User)).all():
        recipient=user.role==target_role if level or item.assigned_user_id is None else user.id==item.assigned_user_id
        if not recipient or not can_access(db,user,item):continue
        row=db.scalar(select(NotificationDelivery).where(NotificationDelivery.incident_id==item.id,NotificationDelivery.user_id==user.id,NotificationDelivery.level==level,NotificationDelivery.channel=='in_app'))
        if row is None:row=NotificationDelivery(incident_id=item.id,user_id=user.id,level=level);db.add(row);db.flush()
        deliver(row)


def emit(db,category,severity,source_key,identity,title=None,detail='',entity_kind=None,entity_id=None):
    if db.scalar(select(IncidentOccurrence.id).where(IncidentOccurrence.source_key==source_key)):return None
    rule=db.scalar(select(NotificationRule).where(NotificationRule.category==category).with_for_update())
    if rule is None:initialize_rules(db);rule=db.scalar(select(NotificationRule).where(NotificationRule.category==category).with_for_update())
    if not rule.enabled or SEVERITIES[severity]<SEVERITIES[rule.minimum_severity]:return None
    key=hashlib.sha256(f'{category}:{identity}'.encode()).hexdigest()
    item=db.scalar(select(Incident).where(Incident.dedup_key==key).with_for_update().execution_options(populate_existing=True))
    now=utcnow();previous_id=None
    if item is not None and item.status=='resolved':
        previous_id=item.id;item.dedup_key=f'{key}:closed:{item.id}';db.flush();item=None
    if item is None:
        item=Incident(dedup_key=key,category=category,severity=severity,title=title or CATEGORIES[category],detail=detail,entity_kind=entity_kind,entity_id=entity_id,assigned_role=rule.assigned_role,assigned_user_id=rule.assigned_user_id,escalation_role=rule.escalation_role,escalation_at=now+timedelta(minutes=rule.escalation_minutes),due_at=now+timedelta(minutes=rule.remediation_minutes))
        db.add(item);db.flush();history(db,item,'created',detail={'source_key':source_key,'rule_version':rule.version,'previous_incident_id':previous_id})
    else:
        item.occurrence_count+=1;item.last_occurred_at=now;item.version+=1
        if SEVERITIES[severity]>SEVERITIES[item.severity]:item.severity=severity
        history(db,item,'recurred',detail={'source_key':source_key})
        for row in db.scalars(select(NotificationDelivery).where(NotificationDelivery.incident_id==item.id)).all():row.read_at=None
    db.add(IncidentOccurrence(incident_id=item.id,source_key=source_key));db.flush();notify(db,item)
    return item


def project_audit(db,event,payload):
    type=event.event_type;category=None;kind=None;id=None;severity='high';identity=None;detail=''
    if type in ('auth.failed','auth.denied','access.role_denied','entity.access_denied'):
        category='unauthorized_access';identity=f'actor-{event.actor_id or "unknown"}';detail='A backend authentication, role or clearance check rejected a request. Credentials and request bodies are withheld.'
    elif type=='policy.permission_denied' or type=='policy.evaluated' and payload.get('outcome')=='denied':
        category='policy_violation';identity=f'{event.actor_id}-{payload.get("operation",payload.get("permission","restricted"))}';detail=f'Backend policy rejected an operation. Policy revision {payload.get("revision_id","unavailable")}.'
    elif type=='integration.run_finished' and payload.get('status')=='failed':
        category='integration_failure';kind='integrations';id=payload['connection_id'];identity=id
        connection=db.get(IntegrationConnection,id);detail=f'{"Synthetic mock" if connection and connection.mode=="mock" else "Live-profile"} integration run failed. Inspect safe run history; no successful synchronization is implied.'
    elif type=='demo.attack_blocked':
        category={'demand_poisoning':'demand_poisoning','inventory_manipulation':'inventory_change','supplier_spoofing':'supplier_spoofing'}.get(payload.get('attack_type'));severity='critical';identity=f'alert-{payload["alert_id"]}' if payload.get('alert_id') else f'demo-{payload.get("sku")}-{category}';detail='Explicit synthetic attack simulation was blocked. This is simulation evidence, not a claim of a real attack.'
        product=db.scalar(select(Product).where(Product.sku==payload.get('sku')));kind='products' if product else None;id=product.id if product else None
    elif type=='import.ingested' and payload.get('quarantined',0)>0:
        category='demand_poisoning';severity='high';identity=f'batch-{payload["batch_id"]}';detail='Import validation quarantined anomalous demand rows. An anomaly is a review signal, not proof of poisoning.'
    elif type=='inventory.movement_created':
        lot=db.get(InventoryLot,payload['lot_id'])
        from ..models import StockMovement
        movement=db.get(StockMovement,payload['id'])
        rule=db.scalar(select(NotificationRule).where(NotificationRule.category=='inventory_change'))
        if lot and (lot.status=='quarantined' or movement and movement.quantity>=(rule.quantity_threshold if rule else 10000)):
            category='inventory_change';severity='critical' if lot.status=='quarantined' else 'high';kind='inventory';id=lot.id;identity=id;detail='A guarded inventory movement exceeded the notification review threshold or affected a quarantined lot. Review the movement; this is a signal, not proof of manipulation.' 
    if category:emit(db,category,severity,f'run-{payload["run_id"]}' if category=='integration_failure' else f'alert-{payload["alert_id"]}' if type=='demo.attack_blocked' and payload.get('alert_id') else f'audit-{event.id}',identity,detail=detail,entity_kind=kind,entity_id=id)


def reconcile(db):
    """Poll actual persistent source state; source keys prevent repeated notifications."""
    from ..audit import acquire_audit_lock
    acquire_audit_lock(db)
    initialize_rules(db);now=utcnow()
    from ..analytics import supplier_risk
    for row in db.scalars(select(Supplier)).all():
        risk=supplier_risk(row.reliability,row.average_lead_time,row.defect_rate,row.price_variance)
        if risk>=80:
            emit(db,'supplier_risk','critical',f'supplier-{row.id}-risk-{risk:.4f}',row.id,detail=f'Stored supplier indicators produce risk score {risk:.1f}. This score is a heuristic; investigate current inputs.',entity_kind='suppliers',entity_id=row.id)
    for row in db.scalars(select(InventoryLot).where(InventoryLot.status=='quarantined')).all():emit(db,'inventory_change','high',f'quarantined-lot-{row.id}',row.id,detail='Inventory lot is quarantined; review import/quality evidence before further movements.',entity_kind='inventory',entity_id=row.id)
    for model,kind in ((Recommendation,'stock'),(ActionProposal,'stage')):
        for decided in db.scalars(select(model).where(model.status.in_(['approved','rejected','dismissed']))).all():
            key=hashlib.sha256(f'pending_approval:{kind}-{decided.id}'.encode()).hexdigest()
            pending=db.scalar(select(Incident).where(Incident.dedup_key==key,Incident.status!='resolved').with_for_update())
            if pending:
                pending.status='resolved';pending.version+=1;pending.resolved_at=now;pending.resolved_by=decided.decided_by;pending.resolution_note=f'Source recommendation decision: {decided.status}'
                history(db,pending,'source_decided',decided.decided_by,{'source_status':decided.status})
                from ..audit import append_audit
                append_audit(db,'notification.source_decided',decided.decided_by,{'incident_id':pending.id,'source_status':decided.status})
        for row in db.scalars(select(model).where(model.status.in_(['pending','deferred']))).all():
            entity_kind='products' if kind=='stock' else 'stage-actions';entity_id=row.product_id if kind=='stock' else row.id
            emit(db,'pending_approval','medium',f'approval-{kind}-{row.id}',f'{kind}-{row.id}',detail=f'{kind.title()} recommendation {row.id} awaits a human decision. Deferral is not approval.',entity_kind=entity_kind,entity_id=entity_id)
            if kind=='stage' and row.due_at and utc_naive(row.due_at)<=now:emit(db,'overdue_remediation','critical' if row.urgency=='critical' else 'high',f'overdue-action-{row.id}-{row.due_at.isoformat()}',f'action-{row.id}',detail='A stage action deadline passed without a final decision.',entity_kind=entity_kind,entity_id=entity_id)
    for task in db.scalars(select(OperationalTask).where(OperationalTask.status.notin_(['completed','cancelled']),OperationalTask.due_at<=now)).all():emit(db,'overdue_remediation','high',f'overdue-task-{task.id}-{task.due_at.isoformat()}',f'task-{task.id}',detail=f'Operational remediation task {task.id} has passed its stored deadline. Inspect the task before resolving.')
    # Existing alerts are real persisted signals, including labeled synthetic seed alerts.
    for alert in db.scalars(select(Alert).where(Alert.status=='open')).all():
        category={'integrity':'demand_poisoning','authentication':'unauthorized_access','authorization':'unauthorized_access','supplier':'supplier_risk'}.get(alert.category)
        if category:emit(db,category,alert.severity if alert.severity in SEVERITIES else 'high',f'alert-{alert.id}',f'alert-{alert.id}',detail=f'Persisted alert {alert.id}: {alert.title}. Review its source; alerts and synthetic simulations are not proof of a real attack.')
    from ..models import IntegrationRecord,RecommendationProgress
    from ..security import decrypt_field
    for record in db.scalars(select(IntegrationRecord).where(IntegrationRecord.resource=='suppliers')).all():
        data=json.loads(decrypt_field(record.encrypted_data))
        if data.get('identity_status')=='disputed' or data.get('compliance_status')=='non_compliant':
            category='supplier_spoofing' if data.get('identity_status')=='disputed' else 'supplier_risk'
            emit(db,category,'critical',f'supplier-source-{record.id}-{record.source_version}',f'source-{record.id}',detail=f'{"Synthetic mock" if record.provenance=="mock" else "Synchronized source"} supplier identity/compliance requires review. Source claims are not independently verified.',entity_kind='integrations',entity_id=record.connection_id)
    for action in db.scalars(select(ActionProposal).where(ActionProposal.status=='approved',ActionProposal.due_at<=now)).all():
        progress=db.scalar(select(RecommendationProgress).where(RecommendationProgress.kind=='stage',RecommendationProgress.source_id==action.id))
        if not progress or progress.implementation_status not in ('completed','cancelled'):
            emit(db,'overdue_remediation','critical' if action.urgency=='critical' else 'high',f'overdue-approved-action-{action.id}-{action.due_at.isoformat()}',f'action-{action.id}',detail='Approved stage action passed its deadline without a reported final implementation outcome.',entity_kind='stage-actions',entity_id=action.id)
    for run in db.scalars(select(IntegrationRun).where(IntegrationRun.status=='failed')).all():
        connection=db.get(IntegrationConnection,run.connection_id)
        emit(db,'integration_failure','high',f'run-{run.id}',run.connection_id,detail=f'{"Synthetic mock" if connection.mode=="mock" else "Live-profile"} connection has a failed run. Inspect integration history.',entity_kind='integrations',entity_id=run.connection_id)
    for incident in db.scalars(select(Incident).where(Incident.status!='resolved').with_for_update()).all():
        if incident.severity=='critical' and incident.escalation_level==0 and utc_naive(incident.escalation_at)<=now or incident.escalation_level==0 and utc_naive(incident.due_at)<=now:
            incident.escalation_level=1;incident.version+=1
            history(db,incident,'escalated',detail={'reason':'critical_unresolved' if incident.severity=='critical' else 'remediation_overdue','to_role':incident.escalation_role})
            notify(db,incident,1)
            from ..audit import append_audit
            append_audit(db,'notification.incident_escalated',None,{'incident_id':incident.id,'level':1,'assigned_role':incident.escalation_role})
    for row in db.scalars(select(NotificationDelivery).where(NotificationDelivery.status=='pending')).all():
        user=db.get(User,row.user_id);incident=db.get(Incident,row.incident_id)
        if incident.status=='resolved':row.status='cancelled';row.error_code='incident_resolved';row.next_attempt_at=None
        elif user and can_access(db,user,incident):deliver(row)
    db.commit()
