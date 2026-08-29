from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import QuarantinedRecord, SaleRecord
from app.security import sign_import


def payload(csv: str) -> dict:
    return {"dataset_name": "test.csv", "csv_content": csv, "signature": sign_import(csv.encode())}


def test_unsigned_or_modified_import_is_rejected(client, auth):
    csv = "sku,date,quantity\nSKU-001,2026-01-01,20\n"
    body = payload(csv)
    body["csv_content"] = csv.replace(",20", ",200")
    response = client.post("/imports", headers=auth("analyst"), json=body)
    assert response.status_code == 400
    assert "signature" in response.json()["detail"].lower()


def test_malformed_import_returns_actionable_schema_error(client, auth):
    csv = "product,when,amount\nSKU-001,2026-01-01,20\n"
    response = client.post("/imports/preview", headers=auth("analyst"), json=payload(csv))
    assert response.status_code == 422
    assert "Missing required columns" in response.json()["detail"]


def test_poisoned_and_unknown_rows_are_quarantined_not_ingested(client, auth):
    csv = "sku,date,quantity\nSKU-001,2026-01-01,20\nSKU-001,2026-01-02,12000\nUNKNOWN,2026-01-03,21\n"
    with SessionLocal() as db:
        before = int(db.scalar(select(func.count(SaleRecord.id))) or 0)
    response = client.post("/imports", headers=auth("analyst"), json=payload(csv))
    assert response.status_code == 200
    result = response.json()
    assert result["accepted_count"] == 1
    assert len(result["quarantined"]) == 2
    with SessionLocal() as db:
        assert int(db.scalar(select(func.count(SaleRecord.id))) or 0) == before + 1
        assert int(db.scalar(select(func.count(QuarantinedRecord.id))) or 0) == 2


def test_duplicate_import_is_idempotently_rejected(client, auth):
    csv = "sku,date,quantity\nSKU-001,2026-01-01,20\n"
    body = payload(csv)
    assert client.post("/imports", headers=auth("analyst"), json=body).status_code == 200
    assert client.post("/imports", headers=auth("analyst"), json=body).status_code == 409

