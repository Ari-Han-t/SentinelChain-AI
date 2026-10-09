def test_template_crud_is_admin_only(client, auth):
    headers = auth("admin")
    created = client.post("/node-templates", headers=headers, json={
        "name": "Cold storage", "key": "cold-storage",
        "field_definitions": [{"name": "temperature", "type": "number"}],
        "enabled_modules": ["inventory", "quality"],
    })
    assert created.status_code == 200
    template_id = created.json()["id"]
    assert client.get("/node-templates", headers=auth("analyst")).status_code == 200
    assert client.delete(f"/node-templates/{template_id}", headers=headers).json()["status"] == "disabled"


def test_inventory_movement_cannot_make_stock_negative(client, auth):
    headers = auth("analyst")
    lot = client.post("/inventory/lots", headers=headers, json={
        "sku": "TEST-1", "lot_number": "LOT-1", "quantity": 5,
    }).json()
    response = client.post("/inventory/movements", headers=headers, json={
        "lot_id": lot["id"], "movement_type": "issue", "quantity": 6,
    })
    assert response.status_code == 422


def test_purchase_order_links_to_shipment_and_tracking(client, auth):
    headers = auth("manager")
    order = client.post("/purchase-orders", headers=headers, json={
        "order_number": "PO-TEST-1", "lines": [{"sku": "TEST-1", "quantity": 2, "unit_cost": 4}],
    }).json()
    shipment = client.post("/shipments", headers=headers, json={
        "shipment_number": "SHIP-TEST-1", "purchase_order_id": order["id"],
    })
    assert shipment.status_code == 200
    event = client.post(f"/shipments/{shipment.json()['id']}/tracking-events", headers=headers, json={"status": "in_transit"})
    assert event.status_code == 200


def test_quality_failure_quarantines_lot(client, auth):
    headers = auth("analyst")
    lot = client.post("/inventory/lots", headers=headers, json={
        "sku": "TEST-2", "lot_number": "LOT-2", "quantity": 3,
    }).json()
    response = client.post("/quality/inspections", headers=headers, json={
        "lot_id": lot["id"], "result": "fail", "quarantine_reason": "Failed seal test",
    })
    assert response.status_code == 200
    assert response.json()["lot_status"] == "quarantined"


def test_risk_and_exception_require_manager_or_admin(client, auth):
    risk = client.post("/risks", headers=auth("analyst"), json={
        "title": "Supplier outage", "likelihood": 3, "impact": 4,
    })
    exception = client.post("/control-tower/exceptions", headers=auth("analyst"), json={
        "title": "Late dispatch",
    })
    assert risk.status_code == 403
    assert exception.status_code == 403
    assert client.post("/risks", headers=auth("manager"), json={
        "title": "Supplier outage", "likelihood": 3, "impact": 4,
    }).status_code == 200
