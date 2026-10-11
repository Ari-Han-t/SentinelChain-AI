"""Add linked fictional operations without replacing existing operational records.
Run from backend: python -m app.operations_demo. Demo environments only.
"""
import hashlib
import json
from datetime import timedelta
from sqlalchemy import select
from .config import settings
from .database import SessionLocal
from .seed import seed_database
from .security import encrypt_field
from .audit import append_audit
from .models import (AuditEvent, User, Role, Product, Supplier, Warehouse, InventoryLot,
    PurchaseOrder, PurchaseOrderLine, Shipment, TrackingEvent, QualityInspection,
    OperationalTask, Risk, NodeTemplate, Workflow, EntityGovernance, EvidenceRecord,
    SupplyChainNode, SupplyChain, DEFAULT_CHAIN_KEY, ControlTowerException, utcnow)

MARKER = 'demo.operations.v1.loaded'

def load_operations_demo():
    if not settings.demo_mode or settings.environment.lower() == 'production':
        raise RuntimeError('Fictional operations are restricted to demo environments')
    seed_database()
    with SessionLocal() as db:
        if db.scalar(select(AuditEvent).where(AuditEvent.event_type == MARKER)):
            return {'status': 'already_loaded'}
        admin = db.scalar(select(User).where(User.role == Role.ADMIN.value))
        manager = db.scalar(select(User).where(User.role == Role.MANAGER.value))
        analyst = db.scalar(select(User).where(User.role == Role.ANALYST.value))
        chain = db.scalar(select(SupplyChain).where(SupplyChain.key == DEFAULT_CHAIN_KEY))
        nodes = {x.stage_type: x for x in db.scalars(select(SupplyChainNode).where(SupplyChainNode.chain_id == chain.id))}
        now = utcnow()
        def add(model, **values):
            item = model(**values); db.add(item); db.flush(); return item
        warehouse = db.scalar(select(Warehouse).where(Warehouse.code == 'DEMO-BLR-01')) or add(Warehouse, code='DEMO-BLR-01', name='Fictional Bengaluru Assembly Warehouse', location='Bengaluru — synthetic location')
        add(Warehouse, code='DEMO-PUN-01', name='Fictional Pune Distribution Hub', location='Pune — synthetic location')
        suppliers = []
        for name, reliability, lead in [('DEMO Nova Precision', .97, 6), ('DEMO Apex Safety', .83, 12), ('DEMO Vector Cable', .94, 5)]:
            suppliers.append(add(Supplier, name=name, reliability=reliability, average_lead_time=lead, defect_rate=.02, price_variance=.05, encrypted_contact=encrypt_field('fictional-contact@example.invalid')))
        lots, orders, shipments = [], [], []
        for index, (sku, quantity, held) in enumerate([('SKU-001',92,0),('SKU-002',38,12),('SKU-003',310,0)]):
            product = db.scalar(select(Product).where(Product.sku == sku))
            # Dedicated lots partition the existing fixture stock; catalog balances are untouched.
            lot = add(InventoryLot, sku=sku, lot_number=f'DEMO-LOT-{index+1:03}', quantity=quantity-held, location=warehouse.name, status='available', received_at=now-timedelta(days=4))
            lots.append(lot)
            add(QualityInspection, lot_id=lot.id, result='pass', quarantine_reason='Fictional receiving sample passed dimensions and electrical checks.', disposition=None, inspected_by=analyst.id)
            if held:
                held_lot = add(InventoryLot, sku=sku, lot_number='DEMO-LOT-002-HOLD', quantity=held, location=warehouse.name, status='quarantined')
                lots.append(held_lot)
                add(QualityInspection, lot_id=held_lot.id, result='fail', quarantine_reason='Fictional relay contact resistance exceeded tolerance; 12 units must not be issued.', disposition='hold', inspected_by=analyst.id)
            order = add(PurchaseOrder, order_number=f'DEMO-PO-{index+1:03}', supplier_id=suppliers[index].id, status='ordered', ordered_at=now-timedelta(days=3), created_by=admin.id)
            orders.append(order)
            add(PurchaseOrderLine, purchase_order_id=order.id, sku=sku, quantity=[200,180,500][index], unit_cost=product.unit_cost)
            shipment = add(Shipment, shipment_number=f'DEMO-SHP-{index+1:03}', purchase_order_id=order.id, status='delayed' if index==1 else 'in_transit', carrier='Fictional Meridian Freight', tracking_number=f'DEMO-TRACK-{index+1:03}', created_by=admin.id)
            shipments.append(shipment)
            add(TrackingEvent, shipment_id=shipment.id, status=shipment.status, location='Fictional consolidation depot', notes='Synthetic carrier report: relay replenishment delayed 3 days.' if index==1 else 'Synthetic shipment departed supplier depot.', occurred_at=now)
        for kind, records, stage in [('suppliers',suppliers,'supplier'),('inventory',lots,'production'),('purchase-orders',orders,'procurement'),('shipments',shipments,'logistics')]:
            for record in records:
                add(EntityGovernance, kind=kind, entity_id=record.id, owner_id=manager.id if kind=='purchase-orders' else analyst.id, stage_id=nodes.get(stage).id if nodes.get(stage) else None, warehouse_id=warehouse.id if kind=='inventory' else None, risk_level='medium', minimum_clearance=1)
        for title, description, owner in [
            ('DEMO: Review relay replenishment', 'SKU-002 has 26 usable units, 12 quarantined units and 180 inbound units on delayed DEMO-PO-002. Confirm arrival before approving an expedite.',manager),
            ('DEMO: Resolve quality hold', 'Inspect DEMO-LOT-002-HOLD and record disposition before releasing its 12 units.',analyst),
            ('DEMO: Confirm inbound freight ETA', 'Contact fictional carrier for DEMO-SHP-002; preserve the revised ETA as evidence.',analyst)]:
            add(OperationalTask,title=title,description=description,priority='high',assigned_to=owner.id,due_at=now+timedelta(days=1),created_by=admin.id)
        for title, description in [('DEMO: Relay availability risk','SKU-002 usable stock is 26 units; quarantine and inbound delay constrain assembly.'),('DEMO: Supplier concentration','DEMO Apex Safety supplies the delayed relay order; qualify a backup before switching sources.')]:
            add(Risk,title=title,description=description,likelihood=4,impact=4,owner_id=manager.id,created_by=admin.id)
        add(ControlTowerException,title='DEMO: Relay quality hold and delayed replenishment',severity='high',category='availability',details='12 SKU-002 units quarantined; DEMO-SHP-002 carries 180 units and is delayed. Review before any material decision.',assigned_to=manager.id,created_by=admin.id)
        for key, name, modules in [('demo-receiving','DEMO Receiving and inspection',['inventory','quality']),('demo-replenishment','DEMO Replenishment planning',['procurement','shipments'])]:
            add(NodeTemplate,key=key,name=name,description='Fictional reusable capability for the classroom supply chain.',enabled_modules_json=json.dumps(modules),field_definitions_json=json.dumps([{'key':'sku','type':'string','required':True}]),created_by=admin.id)
        add(Workflow,name='DEMO: Review relay shortage',trigger_json=json.dumps({'event_type':'inventory.low_stock'}),conditions_json=json.dumps([{'sku':'SKU-002'}]),actions_json=json.dumps([{'type':'create_task','requires_approval':True}]),status='draft',created_by=admin.id)
        summaries = {
            'supplier':'Fictional supplier knowledge: DEMO Apex Safety reliability 83%, typical lead time 12 days; Nova Precision 97%, 6 days; Vector Cable 94%, 5 days.',
            'procurement':'Fictional procurement knowledge: DEMO-PO-002 orders 180 SKU-002 relays; 26 units are usable and 12 quarantined. Confirm delayed arrival before an expedite; human approval required.',
            'production':'Fictional inventory and quality knowledge: SKU-001 92 available; SKU-002 26 available plus 12 quarantined; SKU-003 310 available. Failed relay inspection prevents issuing the held lot.',
            'logistics':'Fictional shipment knowledge: DEMO-SHP-002 replenishes 180 SKU-002 units against DEMO-PO-002 and is delayed 3 days; the other two inbound shipments are in transit.',
        }
        for stage, summary in summaries.items():
            node = nodes.get(stage)
            if not node: continue
            payload = {'synthetic':True,'dataset':'operations-v1','category':stage,'purchase_order_ids':[x.id for x in orders],'lot_ids':[x.id for x in lots],'shipment_ids':[x.id for x in shipments]}
            payload['full_summary'] = summary
            canonical = json.dumps(payload,sort_keys=True,separators=(',',':'))
            event = 'demo.operations.context'
            add(EvidenceRecord,node_id=node.id,source_type='manual',external_id=f'demo-operations-v1-{stage}',event_type=event,summary=summary[:300],payload_json=json.dumps(payload),integrity_digest=hashlib.sha256(f'{event}:{summary[:300]}:{canonical}'.encode()).hexdigest(),confidence=1,status='accepted',actor_id=admin.id,occurred_at=now)
        append_audit(db,MARKER,admin.id,{'synthetic':True,'lots':len(lots),'purchase_orders':len(orders),'shipments':len(shipments),'decision_source':'stage evidence; not live external data'})
        db.commit()
        return {'status':'loaded','lots':len(lots),'purchase_orders':len(orders),'shipments':len(shipments)}

if __name__ == '__main__':
    print(json.dumps(load_operations_demo()))
