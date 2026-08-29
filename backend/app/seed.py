from __future__ import annotations

import math
import random
from datetime import date, timedelta

from sqlalchemy import func, select

from .audit import append_audit
from .database import SessionLocal, init_db
from .models import Alert, Product, Role, SaleRecord, Supplier, User
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
        if (db.scalar(select(func.count(User.id))) or 0) > 0:
            return
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
        db.commit()


if __name__ == "__main__":
    seed_database()

