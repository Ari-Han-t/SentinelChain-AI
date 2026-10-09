from __future__ import annotations

import math
import random
import hashlib
import json
from datetime import date, timedelta

from sqlalchemy import func, select

from .audit import append_audit
from .database import SessionLocal, init_db
from .models import (
    DEFAULT_CHAIN_KEY,
    DEFAULT_CHAIN_NAME,
    Alert,
    EvidenceRecord,
    OrganizationProfile,
    Product,
    Role,
    SaleRecord,
    Supplier,
    SupplyChain,
    SupplyChainEdge,
    SupplyChainNode,
    User,
    UserContext,
)
from .security import encrypt_field, hash_password


DEMO_USERS = [
    ("admin@sentinelchain.local", "Ari Admin", Role.ADMIN),
    ("analyst@sentinelchain.local", "Indra Analyst", Role.ANALYST),
    ("manager@sentinelchain.local", "Priya Manager", Role.MANAGER),
    ("auditor@sentinelchain.local", "Asha Auditor", Role.AUDITOR),
]


def seed_database() -> None:
    init_db()
    with SessionLocal() as db:
        users = db.scalars(select(User).order_by(User.id)).all()
        if not users:
            users = [User(email=email, display_name=name, role=role.value, password_hash=hash_password("demo1234")) for email, name, role in DEMO_USERS]
            db.add_all(users)
            products = [
                Product(sku="SKU-001", name="Industrial Sensor", current_stock=92, unit_cost=42, order_cost=55, holding_cost_rate=0.22, lead_time_days=8),
                Product(sku="SKU-002", name="Safety Relay", current_stock=38, unit_cost=65, order_cost=60, holding_cost_rate=0.2, lead_time_days=12),
                Product(sku="SKU-003", name="Control Cable", current_stock=310, unit_cost=8.5, order_cost=35, holding_cost_rate=0.18, lead_time_days=5),
            ]
            db.add_all(products)
            db.flush()
            rng = random.Random(42)
            start = date.today() - timedelta(days=119)
            for product_index, product in enumerate(products):
                for day in range(120):
                    weekly = 4 * math.sin((day % 7) / 7 * math.tau)
                    trend = day * (0.03 + product_index * 0.005)
                    quantity = max(1, round(18 + product_index * 7 + weekly + trend + rng.gauss(0, 2)))
                    db.add(SaleRecord(product_id=product.id, sold_at=start + timedelta(days=day), quantity=quantity))
            db.add_all(
                [
                    Supplier(name="Nova Components", reliability=0.96, average_lead_time=6.2, defect_rate=0.011, price_variance=0.04, encrypted_contact=encrypt_field("ops@nova.example")),
                    Supplier(name="Apex Industrial", reliability=0.88, average_lead_time=11.4, defect_rate=0.032, price_variance=0.09, encrypted_contact=encrypt_field("supply@apex.example")),
                    Supplier(name="Vector Parts", reliability=0.79, average_lead_time=17.1, defect_rate=0.061, price_variance=0.16, encrypted_contact=encrypt_field("contact@vector.example")),
                ]
            )
            db.add(Alert(category="availability", severity="medium", title="Safety Relay below safety threshold", detail="SKU-002 has 38 units on hand with a 12-day lead time."))
            append_audit(db, "system.seeded", users[0].id, {"synthetic": True, "products": len(products), "days": 120})
            db.flush()

        admin = next(user for user in users if user.role == Role.ADMIN.value)
        if not db.scalar(select(OrganizationProfile)):
            db.add(OrganizationProfile(
                name="Sentinel Industrial Demo",
                industry="Industrial components",
                description="A synthetic manufacturer monitoring component supply, purchasing, assembly, logistics, and customer fulfilment.",
                objectives_json=json.dumps(["Prevent stockouts", "Contain poisoned data", "Keep material actions human-approved"]),
                constraints_json=json.dumps(["Synthetic data only", "No autonomous purchase orders"]),
                updated_by=admin.id,
            ))
        for user in users:
            if not db.scalar(select(UserContext).where(UserContext.user_id == user.id)):
                db.add(UserContext(
                    user_id=user.id,
                    owned_stages_json=json.dumps({
                        Role.ADMIN.value: ["all"],
                        Role.ANALYST.value: ["demand", "inventory", "supplier"],
                        Role.MANAGER.value: ["procurement", "approval"],
                        Role.AUDITOR.value: ["evidence", "audit"],
                    }.get(user.role, [])),
                    decision_limits_json=json.dumps({"material_actions_require_approval": True}),
                    escalation_preferences_json=json.dumps({"severity": "high"}),
                ))
        chain = db.scalar(select(SupplyChain).where(SupplyChain.key == DEFAULT_CHAIN_KEY))
        if chain is None:
            chain = SupplyChain(
                key=DEFAULT_CHAIN_KEY,
                name=DEFAULT_CHAIN_NAME,
                description="Primary demo chain: component suppliers through customer fulfilment.",
                created_by=admin.id,
            )
            db.add(chain)
            db.flush()
        if (db.scalar(select(func.count(SupplyChainNode.id))) or 0) == 0:
            specs = [
                ("demand", "Demand signal", "demand", Role.ANALYST.value, 0, 120, "healthy"),
                ("supplier", "Component suppliers", "supplier", Role.ANALYST.value, 260, 40, "at_risk"),
                ("procurement", "Procurement", "procurement", Role.MANAGER.value, 520, 120, "healthy"),
                ("production", "Production", "production", Role.ANALYST.value, 780, 40, "healthy"),
                ("logistics", "Outbound logistics", "logistics", Role.ANALYST.value, 1040, 120, "healthy"),
                ("customer", "Customer fulfilment", "customer", Role.MANAGER.value, 1300, 40, "healthy"),
            ]
            nodes = [
                SupplyChainNode(chain_id=chain.id, key=key, name=name, stage_type=stage, owner_role=owner, position_x=x, position_y=y, status=status)
                for key, name, stage, owner, x, y, status in specs
            ]
            db.add_all(nodes)
            db.flush()
            for source, target, label in zip(nodes[:-1], nodes[1:], ["demand plan", "purchase request", "materials", "finished goods", "delivery"], strict=True):
                db.add(SupplyChainEdge(source_node_id=source.id, target_node_id=target.id, label=label, status="at_risk" if source.key == "supplier" else "healthy"))
            summary = "Apex Industrial lead time increased to 17.1 days; Safety Relay cover is below the replenishment horizon."
            db.add(EvidenceRecord(
                node_id=nodes[1].id,
                source_type="api",
                external_id="seed-supplier-delay",
                event_type="supplier.delay",
                summary=summary,
                payload_json=json.dumps({"supplier": "Apex Industrial", "lead_time_days": 17.1, "sku": "SKU-002"}),
                integrity_digest=hashlib.sha256(summary.encode()).hexdigest(),
                confidence=0.97,
            ))
        db.commit()


def bootstrap_admin(email: str, password: str) -> None:
    """Create the first production administrator exactly once."""
    init_db()
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == email.lower())):
            return
        admin = User(email=email.lower(), display_name="SentinelChain Admin", role=Role.ADMIN.value, password_hash=hash_password(password))
        db.add(admin)
        db.flush()
        append_audit(db, "admin.bootstrapped", admin.id, {"email": admin.email})
        db.commit()


if __name__ == "__main__":
    seed_database()
