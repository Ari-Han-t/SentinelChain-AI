def test_forecast_recommendation_and_human_approval_flow(client, auth):
    analyst = auth("analyst")
    trained = client.post("/forecasts/SKU-001/train", headers=analyst)
    assert trained.status_code == 200
    forecast = trained.json()
    assert forecast["model_name"] in {"XGBoost", "GradientBoosting fallback"}
    assert forecast["mae"] >= 0
    assert forecast["baseline_mae"] >= 0
    assert len(forecast["explanation"]) == 5

    generated = client.post("/recommendations/generate/SKU-001", headers=analyst)
    assert generated.status_code == 200
    recommendation = generated.json()
    assert recommendation["status"] == "pending"
    assert recommendation["recommended_quantity"] >= 0

    manager = auth("manager")
    approved = client.post(
        f"/recommendations/{recommendation['id']}/decision",
        headers=manager,
        json={"decision": "approved", "expected_status": "pending", "note": "Lead time checked"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    duplicate = client.post(
        f"/recommendations/{recommendation['id']}/decision",
        headers=manager,
        json={"decision": "rejected", "expected_status": "pending"},
    )
    assert duplicate.status_code == 409


def test_admin_attack_demo_contrasts_unsafe_and_protected_decisions(client, auth):
    response = client.post(
        "/demo/attacks",
        headers=auth("admin"),
        json={"attack_type": "demand_poisoning", "sku": "SKU-001"},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["detected"] is True
    assert result["quarantined"] is True
    assert result["unsafe_decision"]["purchase_quantity"] > result["protected_decision"]["purchase_quantity"]


def test_auditor_can_verify_chain_but_cannot_run_attack(client, auth):
    auditor = auth("auditor")
    chain = client.get("/audit", headers=auditor)
    assert chain.status_code == 200
    assert chain.json()["valid"] is True
    denied = client.post("/demo/attacks", headers=auditor, json={"attack_type": "supplier_spoofing", "sku": "SKU-001"})
    assert denied.status_code == 403

