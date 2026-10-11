import json
from sqlalchemy import select, func
from app.database import SessionLocal
from app.operations_demo import load_operations_demo
from app.models import InventoryLot, QualityInspection, Product, EvidenceRecord, PurchaseOrder, Shipment
from app.audit import verify_chain


def test_linked_demo_is_idempotent_preserves_stock_and_supplies_guidance(client,auth):
    with SessionLocal() as db:
        before=[(p.id,p.current_stock) for p in db.scalars(select(Product))]
    assert load_operations_demo()['status']=='loaded'
    assert load_operations_demo()['status']=='already_loaded'
    with SessionLocal() as db:
        assert before==[(p.id,p.current_stock) for p in db.scalars(select(Product))]
        relay=db.scalars(select(InventoryLot).where(InventoryLot.sku=='SKU-002')).all()
        assert sum(x.quantity for x in relay)==38
        assert sum(x.quantity for x in relay if x.status=='available')==26
        held=next(x for x in relay if x.status=='quarantined')
        assert db.scalar(select(QualityInspection).where(QualityInspection.lot_id==held.id)).result=='fail'
        shipment=db.scalar(select(Shipment).where(Shipment.shipment_number=='DEMO-SHP-002'))
        assert db.get(PurchaseOrder,shipment.purchase_order_id).order_number=='DEMO-PO-002'
        evidence=db.scalars(select(EvidenceRecord).where(EvidenceRecord.external_id.like('demo-operations-v1-%'))).all()
        assert len(evidence)==4 and all(json.loads(x.payload_json)['synthetic'] for x in evidence)
        node_id=next(x.node_id for x in evidence if 'procurement' in x.external_id)
        assert verify_chain(db)==(True,None)
    headers=auth()
    assert len(client.get('/inventory/lots',headers=headers).json())==4
    quality=client.get('/quality/inspections',headers=headers)
    assert quality.status_code==200 and len(quality.json())==4
    assert sum(x['result']=='fail' for x in quality.json())==1
    from app.models import EntityGovernance
    with SessionLocal() as db:
        db.scalar(select(EntityGovernance).where(EntityGovernance.kind=='inventory',EntityGovernance.entity_id==held.id)).minimum_clearance=4
        db.commit()
    assert held.id not in [x['lot_id'] for x in client.get('/quality/inspections',headers=auth('analyst')).json()]
    # Actual recommendation path must consume persisted evidence, not a mocked card.
    from app.main import _run_node_guidance
    from app.models import SupplyChainNode
    with SessionLocal() as db:
        run,_=_run_node_guidance(db,db.get(SupplyChainNode,node_id),None)
        assert '180' in run.rationale and 'Fictional' in run.rationale


def test_demo_loader_refuses_production(monkeypatch):
    import pytest
    from app.config import settings
    monkeypatch.setattr(settings,'environment','production')
    with pytest.raises(RuntimeError,match='demo environments'):
        load_operations_demo()
