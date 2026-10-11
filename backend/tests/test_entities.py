import json
import pytest
from app.database import SessionLocal
from app.models import Supplier
from app.security import decrypt_field

SUPPLIER = dict(name="Managed supplier", reliability=.9, average_lead_time=7, defect_rate=.01, price_variance=.02, contact="private@example.invalid")
PRODUCT = dict(sku="PHASE-1", name="Managed item", current_stock=10, unit_cost=5)

def body(data, **governance):
    return dict(data=data, governance=governance, reason="Phase 1 validation")

def create(client, h, kind, data, **g):
    response = client.post(f"/entities/{kind}", headers=h, json=body(data, **g))
    assert response.status_code == 201, response.text
    return response.json()

@pytest.mark.parametrize("role", ["analyst", "manager", "auditor"])
def test_mutations_admin_only(client, auth, role):
    h = auth(role)
    assert client.post("/entities/suppliers", headers=h, json=body(SUPPLIER)).status_code == 403
    assert client.put("/entities/suppliers/1", headers=h, json=body(SUPPLIER)).status_code == 403
    assert client.post("/entities/suppliers/1/state", headers=h, json=dict(active=False, expected_version=1, reason="Retire record")).status_code == 403
    assert client.get("/entities/users", headers=h).status_code == 403

def test_crud_encryption_and_audit(client, auth):
    h = auth(); e = create(client, h, "suppliers", SUPPLIER)
    assert "contact" not in e["data"] and "encrypted_contact" not in e["data"]
    with SessionLocal() as db:
        assert decrypt_field(db.get(Supplier, e["id"]).encrypted_contact) == SUPPLIER["contact"]
    path = f"/entities/suppliers/{e['id']}"
    update = dict(**body({**SUPPLIER, "name": "Renamed supplier"}, risk_level="high"), expected_version=1)
    response = client.put(path, headers=h, json=update)
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2
    assert client.put(path, headers=h, json=update).status_code == 409
    state = dict(active=False, expected_version=2, reason="End supplier relationship")
    assert client.post(path+"/state", headers=h, json=state).json()["active"] is False
    assert client.put(path, headers=h, json={**update, "expected_version": 3}).status_code == 409
    state.update(active=True, expected_version=3)
    assert client.post(path+"/state", headers=h, json=state).json()["version"] == 4
    assert len(client.get(path, headers=h).json()["audit"]) == 4
    audit = client.get("/audit", headers=h).json()
    assert audit["valid"] and SUPPLIER["contact"] not in json.dumps(audit)

def test_clearance_protects_legacy_routes(client, auth):
    h = auth(); e = create(client, h, "suppliers", SUPPLIER, minimum_clearance=4)
    a = auth("analyst")
    for path in ("/entities/suppliers", "/suppliers"):
        assert e["id"] not in [r["id"] for r in client.get(path, headers=a).json()]
    assert client.get(f"/entities/suppliers/{e['id']}", headers=a).status_code == 403
    assert client.post("/purchase-orders", headers=auth("manager"), json=dict(order_number="BYPASS", supplier_id=e["id"])).status_code == 403
    p = create(client, h, "products", PRODUCT, minimum_clearance=4)
    assert client.get("/forecasts/PHASE-1", headers=a).status_code == 403
    assert client.post("/forecasts/PHASE-1/train", headers=a).status_code == 403
    assert "PHASE-1" not in [r["sku"] for r in client.get("/dashboard", headers=a).json()["products"]]
    assert client.post("/inventory/lots", headers=a, json=dict(sku="PHASE-1", lot_number="BYPASS", quantity=1)).status_code == 403
    client.post(f"/entities/products/{p['id']}/state", headers=h, json=dict(active=False, expected_version=1, reason="Retire product"))
    assert client.post("/forecasts/PHASE-1/train", headers=h).status_code == 409

@pytest.mark.parametrize("data,g", [({**SUPPLIER, "reliability": 2}, {}), ({**SUPPLIER, "name": "  "}, {}), ({**SUPPLIER, "role": "administrator"}, {}), (SUPPLIER, {"owner_id": 99999}), (SUPPLIER, {"stage_id": 99999}), (SUPPLIER, {"minimum_clearance": 0})])
def test_invalid_inputs_do_not_persist(client, auth, data, g):
    h = auth(); before = client.get("/entities/suppliers", headers=h).json()
    result = client.post("/entities/suppliers", headers=h, json=body(data, **g))
    assert result.status_code == 422, result.text
    assert client.get("/entities/suppliers", headers=h).json() == before

def test_relationships_and_stock_history(client, auth):
    h = auth(); supplier = create(client, h, "suppliers", SUPPLIER)
    product = create(client, h, "products", PRODUCT)
    warehouse = create(client, h, "warehouses", dict(code="W1", name="Main warehouse"))
    lot = create(client, h, "inventory", dict(sku="PHASE-1", lot_number="L1", quantity=5), warehouse_id=warehouse["id"])
    order = create(client, h, "purchase-orders", dict(order_number="PO1", supplier_id=supplier["id"], lines=[dict(sku="PHASE-1", quantity=2, unit_cost=5)]))
    shipment = create(client, h, "shipments", dict(shipment_number="SH1", purchase_order_id=order["id"]))
    assert client.get(f"/entities/suppliers/{supplier['id']}", headers=h).json()["related"]["purchase_orders"][0]["id"] == order["id"]
    assert client.get(f"/entities/purchase-orders/{order['id']}", headers=h).json()["related"]["shipments"][0]["id"] == shipment["id"]
    assert client.get(f"/entities/warehouses/{warehouse['id']}", headers=h).json()["related"]["inventory"][0]["id"] == lot["id"]
    response = client.put(f"/entities/inventory/{lot['id']}", headers=h, json=dict(**body(dict(sku="PHASE-1", lot_number="L1", quantity=8), warehouse_id=warehouse["id"]), expected_version=1))
    assert response.status_code == 200, response.text
    assert client.get(f"/entities/inventory/{lot['id']}", headers=h).json()["related"]["movements"][0]["quantity"] == 3
    assert client.get("/entities/products?q=managed&sort=risk&status=active", headers=h).json()[0]["id"] == product["id"]
    client.post(f"/entities/inventory/{lot['id']}/state", headers=h, json=dict(active=False, expected_version=2, reason="Retire damaged lot"))
    assert client.post("/inventory/movements", headers=h, json=dict(lot_id=lot["id"], movement_type="issue", quantity=1)).status_code == 409
    assert client.post("/quality/inspections", headers=h, json=dict(lot_id=lot["id"], result="pass")).status_code == 409

def test_unknown_duplicate_and_authentication(client, auth):
    h = auth()
    assert client.get("/entities/suppliers").status_code == 401
    assert client.get("/entities/unknown", headers=h).status_code == 404
    create(client, h, "suppliers", SUPPLIER)
    assert client.post("/entities/suppliers", headers=h, json=body(SUPPLIER)).status_code == 409
    assert client.get("/audit", headers=h).json()["valid"]

def test_parent_clearance_and_retirement_propagate_to_children(client, auth):
    h = auth(); supplier = create(client, h, "suppliers", SUPPLIER, minimum_clearance=4)
    product = create(client, h, "products", PRODUCT)
    order = create(client, h, "purchase-orders", dict(order_number="PO-PARENT", supplier_id=supplier["id"], lines=[dict(sku="PHASE-1", quantity=1, unit_cost=5)]))
    shipment = create(client, h, "shipments", dict(shipment_number="SH-PARENT", purchase_order_id=order["id"]))
    analyst = auth("analyst")
    assert client.get(f"/entities/purchase-orders/{order['id']}", headers=analyst).status_code == 403
    assert client.get(f"/shipments/{shipment['id']}/tracking-events", headers=analyst).status_code == 403
    assert order["id"] not in [r["id"] for r in client.get("/purchase-orders", headers=analyst).json()]
    lot = create(client, h, "inventory", dict(sku="PHASE-1", lot_number="PARENT-LOT", quantity=5))
    client.post(f"/entities/products/{product['id']}/state", headers=h, json=dict(active=False, expected_version=1, reason="Retire product"))
    assert client.post("/inventory/movements", headers=h, json=dict(lot_id=lot["id"], movement_type="issue", quantity=1)).status_code == 409


def test_legacy_movement_invalidates_management_version(client, auth):
    h = auth(); create(client, h, "products", PRODUCT)
    lot = create(client, h, "inventory", dict(sku="PHASE-1", lot_number="VERSION-LOT", quantity=5))
    assert client.post("/inventory/movements", headers=h, json=dict(lot_id=lot["id"], movement_type="receipt", quantity=1)).status_code == 200
    response = client.put(f"/entities/inventory/{lot['id']}", headers=h, json=dict(**body(dict(sku="PHASE-1", lot_number="VERSION-LOT", quantity=7)), expected_version=1))
    assert response.status_code == 409


def test_linked_stage_evidence_and_approvals_are_real_records(client, auth):
    h = auth()
    stage = client.get("/supply-chain", headers=h).json()["nodes"][0]
    entity = create(client, h, "products", PRODUCT, stage_id=stage["id"], owner_id=1)
    response = client.get(f"/entities/products/{entity['id']}", headers=h)
    assert response.status_code == 200
    related = response.json()["related"]
    assert related["stage"][0]["id"] == stage["id"]
    assert all(row["node_id"] == stage["id"] for row in related["evidence"])
    assert "approvals" in related and "guidance" in related
    assert "alerts" not in related


def test_order_lines_are_typed_and_unknown_skus_rejected(client, auth):
    h = auth()
    for lines in ([{"sku": "UNKNOWN", "quantity": 1, "unit_cost": 2}], [{"quantity": "bad"}], []):
        response = client.post("/entities/purchase-orders", headers=h, json=body(dict(order_number="BAD-PO", lines=lines)))
        assert response.status_code == 422, response.text
    assert client.get("/entities/purchase-orders", headers=h).json() == []


def test_global_audit_does_not_expose_restricted_entity_payloads(client, auth):
    h = auth()
    create(client, h, "suppliers", {**SUPPLIER, "name": "Restricted confidential supplier"}, minimum_clearance=4)
    audit = client.get("/audit", headers=auth("auditor")).json()
    assert audit["valid"]
    assert "Restricted confidential supplier" not in json.dumps(audit)
