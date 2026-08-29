from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import date, timedelta

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .analytics import DatasetError, analyze_sales, inventory_policy, parse_sales_csv, supplier_risk, train_forecast
from .audit import append_audit, verify_chain
from .config import settings
from .database import get_db, init_db
from .models import (
    Alert,
    AuditEvent,
    Forecast,
    ImportBatch,
    Product,
    QuarantinedRecord,
    Recommendation,
    Role,
    SaleRecord,
    Supplier,
    User,
)
from .schemas import AttackRequest, DecisionRequest, ImportRequest, LoginRequest, TokenResponse
from .security import create_access_token, get_current_user, require_roles, sign_import, verify_import_signature, verify_password
from .seed import seed_database


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if settings.seed_demo_data:
        seed_database()
    yield


app = FastAPI(
    title="SentinelChain AI API",
    version="1.0.0",
    description="Security-first inventory intelligence with a synthetic-data demo.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

request_windows: dict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    now = time.monotonic()
    key = request.client.host if request.client else "unknown"
    window = request_windows[key]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= settings.rate_limit_per_minute:
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"}, headers={"Retry-After": "60"})
    window.append(now)
    return await call_next(request)


def user_json(user: User) -> dict:
    return {"id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role}


def alert_json(alert: Alert) -> dict:
    return {
        "id": alert.id,
        "category": alert.category,
        "severity": alert.severity,
        "title": alert.title,
        "detail": alert.detail,
        "status": alert.status,
        "created_at": alert.created_at,
    }


def recommendation_json(item: Recommendation, product: Product | None = None) -> dict:
    return {
        "id": item.id,
        "sku": product.sku if product else None,
        "product_name": product.name if product else None,
        "reorder_point": item.reorder_point,
        "safety_stock": item.safety_stock,
        "eoq": item.eoq,
        "recommended_quantity": item.recommended_quantity,
        "supplier_risk": item.supplier_risk,
        "status": item.status,
        "decision_note": item.decision_note,
        "created_at": item.created_at,
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "sentinelchain-api"}


@app.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    append_audit(db, "auth.login", user.id, {"email": user.email})
    db.commit()
    return TokenResponse(access_token=create_access_token(user), user=user_json(user))


@app.get("/auth/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return user_json(user)


@app.get("/dashboard")
def dashboard(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    products = db.scalars(select(Product).order_by(Product.sku)).all()
    alerts = db.scalars(select(Alert).where(Alert.status == "open").order_by(Alert.created_at.desc()).limit(5)).all()
    recommendations = db.scalars(select(Recommendation).order_by(Recommendation.created_at.desc()).limit(5)).all()
    recent_start = date.today() - timedelta(days=29)
    sales = db.execute(
        select(SaleRecord.sold_at, func.sum(SaleRecord.quantity))
        .where(SaleRecord.sold_at >= recent_start)
        .group_by(SaleRecord.sold_at)
        .order_by(SaleRecord.sold_at)
    ).all()
    product_map = {product.id: product for product in products}
    low_stock = sum(1 for product in products if product.current_stock < product.lead_time_days * 10)
    return {
        "synthetic": True,
        "kpis": {
            "total_skus": len(products),
            "low_stock_skus": low_stock,
            "open_security_alerts": sum(1 for alert in alerts if alert.category in {"integrity", "authentication", "authorization"}),
            "pending_approvals": sum(1 for item in recommendations if item.status == "pending"),
        },
        "demand_series": [{"date": sold_at.isoformat(), "quantity": round(float(quantity), 1)} for sold_at, quantity in sales],
        "products": [
            {
                "sku": product.sku,
                "name": product.name,
                "current_stock": product.current_stock,
                "lead_time_days": product.lead_time_days,
                "health": "critical" if product.current_stock < product.lead_time_days * 5 else "watch" if product.current_stock < product.lead_time_days * 10 else "healthy",
            }
            for product in products
        ],
        "alerts": [alert_json(alert) for alert in alerts],
        "recommendations": [recommendation_json(item, product_map.get(item.product_id)) for item in recommendations],
    }


def _prepare_import(body: ImportRequest) -> tuple[bytes, object]:
    content = body.csv_content.encode()
    if not verify_import_signature(content, body.signature):
        raise HTTPException(status_code=400, detail="Manifest signature does not match the dataset")
    try:
        return content, analyze_sales(parse_sales_csv(body.csv_content))
    except DatasetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/imports/preview")
def preview_import(
    body: ImportRequest,
    _: User = Depends(require_roles(Role.ADMIN, Role.ANALYST)),
) -> dict:
    content, analysis = _prepare_import(body)
    return {
        "dataset_name": body.dataset_name,
        "digest": hashlib.sha256(content).hexdigest(),
        "row_count": len(analysis.frame),
        "accepted_count": len(analysis.accepted_indices),
        "quarantined": analysis.quarantined,
        "signature_valid": True,
    }


@app.post("/imports")
def ingest_import(
    body: ImportRequest,
    user: User = Depends(require_roles(Role.ADMIN, Role.ANALYST)),
    db: Session = Depends(get_db),
) -> dict:
    content, analysis = _prepare_import(body)
    digest = hashlib.sha256(content).hexdigest()
    if db.scalar(select(ImportBatch).where(ImportBatch.digest == digest)):
        raise HTTPException(status_code=409, detail="This exact dataset has already been imported")
    batch = ImportBatch(
        dataset_name=body.dataset_name,
        digest=digest,
        status="quarantined" if analysis.quarantined else "accepted",
        row_count=len(analysis.frame),
        quarantined_count=len(analysis.quarantined),
        created_by=user.id,
    )
    db.add(batch)
    db.flush()
    product_map = {item.sku: item for item in db.scalars(select(Product)).all()}
    accepted = 0
    quarantined = list(analysis.quarantined)
    quarantined_indexes = {item["row_number"] - 2 for item in quarantined}
    for index in analysis.accepted_indices:
        row = analysis.frame.loc[index]
        product = product_map.get(str(row["sku"]))
        if product is None:
            quarantined_indexes.add(index)
            quarantined.append(
                {
                    "row_number": index + 2,
                    "record": {"sku": str(row["sku"]), "date": row["date"].date().isoformat(), "quantity": float(row["quantity"])},
                    "reason": "unknown SKU",
                }
            )
            continue
        db.add(SaleRecord(product_id=product.id, sold_at=row["date"].date(), quantity=float(row["quantity"]), source_import_id=batch.id))
        accepted += 1
    for item in quarantined:
        db.add(
            QuarantinedRecord(
                import_batch_id=batch.id,
                row_number=item["row_number"],
                payload_json=json.dumps(item["record"], sort_keys=True),
                reason=item["reason"],
            )
        )
    batch.quarantined_count = len(quarantined)
    batch.status = "quarantined" if quarantined else "accepted"
    if quarantined:
        db.add(
            Alert(
                category="integrity",
                severity="high",
                title=f"{len(quarantined)} import record(s) quarantined",
                detail=f"{body.dataset_name} contained records that failed anomaly or business-rule checks.",
            )
        )
    append_audit(db, "import.ingested", user.id, {"batch_id": batch.id, "digest": digest, "accepted": accepted, "quarantined": len(quarantined)})
    db.commit()
    return {"id": batch.id, "status": batch.status, "accepted_count": accepted, "quarantined": quarantined, "digest": digest}


@app.post("/forecasts/{sku}/train")
def create_forecast(
    sku: str,
    user: User = Depends(require_roles(Role.ADMIN, Role.ANALYST)),
    db: Session = Depends(get_db),
) -> dict:
    product = db.scalar(select(Product).where(Product.sku == sku))
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    records = db.scalars(select(SaleRecord).where(SaleRecord.product_id == product.id).order_by(SaleRecord.sold_at)).all()
    try:
        result = train_forecast(pd.DataFrame([{"date": row.sold_at, "quantity": row.quantity} for row in records]))
    except DatasetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    forecast = Forecast(
        product_id=product.id,
        horizon_days=14,
        daily_demand=result["daily_demand"],
        mae=result["mae"],
        rmse=result["rmse"],
        mape=result["mape"],
        baseline_mae=result["baseline_mae"],
        model_name=result["model_name"],
        explanation_json=json.dumps(result["explanation"]),
    )
    db.add(forecast)
    db.flush()
    append_audit(db, "forecast.trained", user.id, {"forecast_id": forecast.id, "sku": sku, "model": forecast.model_name})
    db.commit()
    return {"id": forecast.id, "sku": sku, **result, "horizon_days": 14, "synthetic": True}


@app.get("/forecasts/{sku}")
def latest_forecast(sku: str, _: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    product = db.scalar(select(Product).where(Product.sku == sku))
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    forecast = db.scalar(select(Forecast).where(Forecast.product_id == product.id).order_by(Forecast.created_at.desc()).limit(1))
    if forecast is None:
        raise HTTPException(status_code=404, detail="No forecast has been trained for this product")
    return {
        "id": forecast.id,
        "sku": sku,
        "daily_demand": forecast.daily_demand,
        "mae": forecast.mae,
        "rmse": forecast.rmse,
        "mape": forecast.mape,
        "baseline_mae": forecast.baseline_mae,
        "model_name": forecast.model_name,
        "explanation": json.loads(forecast.explanation_json),
        "created_at": forecast.created_at,
    }


@app.post("/recommendations/generate/{sku}")
def generate_recommendation(
    sku: str,
    user: User = Depends(require_roles(Role.ADMIN, Role.ANALYST)),
    db: Session = Depends(get_db),
) -> dict:
    product = db.scalar(select(Product).where(Product.sku == sku))
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    forecast = db.scalar(select(Forecast).where(Forecast.product_id == product.id).order_by(Forecast.created_at.desc()).limit(1))
    if forecast is None:
        raise HTTPException(status_code=409, detail="Train a forecast before generating a recommendation")
    quantities = [float(value) for value in db.scalars(select(SaleRecord.quantity).where(SaleRecord.product_id == product.id)).all()]
    annual_demand = sum(quantities[-90:]) / min(len(quantities), 90) * 365
    policy = inventory_policy(
        forecast.daily_demand,
        float(pd.Series(quantities[-30:]).std() or 0),
        product.lead_time_days,
        annual_demand,
        product.order_cost,
        product.unit_cost,
        product.holding_cost_rate,
        product.current_stock,
    )
    suppliers = db.scalars(select(Supplier)).all()
    risk = min((supplier_risk(s.reliability, s.average_lead_time, s.defect_rate, s.price_variance) for s in suppliers), default=100.0)
    item = Recommendation(product_id=product.id, forecast_id=forecast.id, supplier_risk=risk, **policy)
    db.add(item)
    db.flush()
    append_audit(db, "recommendation.generated", user.id, {"recommendation_id": item.id, "sku": sku, **policy, "supplier_risk": risk})
    db.commit()
    return recommendation_json(item, product)


@app.get("/recommendations")
def recommendations(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    items = db.scalars(select(Recommendation).order_by(Recommendation.created_at.desc())).all()
    products = {item.id: item for item in db.scalars(select(Product)).all()}
    return [recommendation_json(item, products.get(item.product_id)) for item in items]


@app.post("/recommendations/{recommendation_id}/decision")
def decide_recommendation(
    recommendation_id: int,
    body: DecisionRequest,
    user: User = Depends(require_roles(Role.ADMIN, Role.MANAGER)),
    db: Session = Depends(get_db),
) -> dict:
    result = db.execute(
        update(Recommendation)
        .where(Recommendation.id == recommendation_id, Recommendation.status == body.expected_status)
        .values(status=body.decision, decided_by=user.id, decision_note=body.note)
    )
    if result.rowcount == 0:
        existing = db.get(Recommendation, recommendation_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        raise HTTPException(status_code=409, detail=f"Recommendation is already {existing.status}")
    item = db.get(Recommendation, recommendation_id)
    append_audit(db, f"recommendation.{body.decision}", user.id, {"recommendation_id": recommendation_id, "note": body.note})
    db.commit()
    return recommendation_json(item)


@app.get("/suppliers")
def suppliers(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Supplier).order_by(Supplier.name)).all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "reliability": row.reliability,
            "average_lead_time": row.average_lead_time,
            "defect_rate": row.defect_rate,
            "price_variance": row.price_variance,
            "risk_score": supplier_risk(row.reliability, row.average_lead_time, row.defect_rate, row.price_variance),
        }
        for row in rows
    ]


@app.get("/alerts")
def alerts(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [alert_json(item) for item in db.scalars(select(Alert).order_by(Alert.created_at.desc())).all()]


@app.get("/audit")
def audit_history(
    _: User = Depends(require_roles(Role.ADMIN, Role.AUDITOR)),
    db: Session = Depends(get_db),
) -> dict:
    valid, broken_at = verify_chain(db)
    events = db.scalars(select(AuditEvent).order_by(AuditEvent.sequence.desc()).limit(100)).all()
    return {
        "valid": valid,
        "broken_at": broken_at,
        "events": [
            {
                "sequence": event.sequence,
                "event_type": event.event_type,
                "actor_id": event.actor_id,
                "payload": json.loads(event.payload_json),
                "previous_hash": event.previous_hash,
                "event_hash": event.event_hash,
                "created_at": event.created_at,
            }
            for event in events
        ],
    }


@app.post("/demo/attacks")
def run_attack(
    body: AttackRequest,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail="Demo attack utility is disabled")
    product = db.scalar(select(Product).where(Product.sku == body.sku))
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    attack_details = {
        "demand_poisoning": ("integrity", "Injected demand spike quarantined", "quantity=12000", 12000),
        "inventory_manipulation": ("integrity", "Impossible inventory adjustment blocked", "stock=-500", 500),
        "supplier_spoofing": ("authentication", "Unverified supplier identity blocked", "supplier=Nova Components LLC", 800),
    }
    category, title, evidence, unsafe_quantity = attack_details[body.attack_type]
    alert = Alert(category=category, severity="critical", title=title, detail=f"Demo-only {body.attack_type.replace('_', ' ')} attempt for {body.sku}: {evidence}.")
    db.add(alert)
    # Demo attacks have no real import batch; preserve evidence in the audit and alert stores.
    append_audit(db, "demo.attack_blocked", user.id, {"attack_type": body.attack_type, "sku": body.sku, "evidence": evidence})
    db.commit()
    safe_quantity = max(0, round(product.lead_time_days * 24 - product.current_stock))
    return {
        "attack_type": body.attack_type,
        "detected": True,
        "quarantined": True,
        "alert_id": alert.id,
        "unsafe_decision": {"purchase_quantity": unsafe_quantity, "source": "compromised input"},
        "protected_decision": {"purchase_quantity": safe_quantity, "source": "last verified data"},
        "message": "Compromised input was blocked before forecasting or approval.",
    }
