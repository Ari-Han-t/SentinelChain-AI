"""Load a rich, deterministic classroom dataset into a demo database.

The loader is intentionally separate from the small test seed.  It can be run
against the Docker database with ``python -m app.demo_data`` and is idempotent.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from .analytics import inventory_policy, supplier_risk
from .audit import append_audit
from .database import SessionLocal
from .guidance import context_digest
from .models import (
    DEFAULT_CHAIN_KEY,
    DEFAULT_CHAIN_NAME,
    ActionProposal,
    Alert,
    AuditEvent,
    EvidenceRecord,
    Forecast,
    GuidanceRun,
    ImportBatch,
    OrganizationProfile,
    Product,
    QuarantinedRecord,
    Recommendation,
    Role,
    SaleRecord,
    Supplier,
    SupplyChain,
    SupplyChainEdge,
    SupplyChainNode,
    User,
    utcnow,
)
from .security import encrypt_field
from .seed import seed_database


DATASET_VERSION = "classroom-v1"
MARKER_EVENT = f"demo.rich_dataset.loaded.{DATASET_VERSION}"


PRODUCTS = [
    ("SKU-001", "Industrial Sensor", 92, 42.0, 55.0, 0.22, 8, 22),
    ("SKU-002", "Safety Relay", 38, 65.0, 60.0, 0.20, 12, 29),
    ("SKU-003", "Control Cable", 310, 8.5, 35.0, 0.18, 5, 36),
    ("SKU-004", "Edge Controller", 24, 148.0, 85.0, 0.24, 21, 13),
    ("SKU-005", "24V Power Module", 57, 71.0, 62.0, 0.21, 14, 19),
    ("SKU-006", "Terminal Block Kit", 480, 4.8, 28.0, 0.16, 4, 45),
    ("SKU-007", "HMI Touch Panel", 19, 226.0, 95.0, 0.25, 28, 9),
    ("SKU-008", "Circuit Breaker", 76, 31.0, 48.0, 0.19, 10, 25),
    ("SKU-009", "Enclosure Cooling Fan", 145, 22.0, 45.0, 0.18, 9, 17),
    ("SKU-010", "DIN Rail Power Supply", 44, 89.0, 72.0, 0.23, 16, 16),
    ("SKU-011", "Secure IIoT Gateway", 12, 315.0, 110.0, 0.27, 30, 7),
    ("SKU-012", "Servo Drive", 31, 184.0, 90.0, 0.24, 24, 11),
]


SUPPLIERS = [
    ("Nova Components", 0.96, 6.2, 0.011, 0.04, "ops@nova.example"),
    ("Apex Industrial", 0.88, 17.1, 0.032, 0.09, "supply@apex.example"),
    ("Vector Parts", 0.79, 17.1, 0.061, 0.16, "contact@vector.example"),
    ("Orion Controls", 0.94, 9.3, 0.014, 0.05, "dispatch@orion.example"),
    ("Helix Electronics", 0.91, 13.8, 0.022, 0.08, "orders@helix.example"),
    ("Meridian Power", 0.84, 19.5, 0.038, 0.13, "fulfilment@meridian.example"),
    ("Kaveri Connectors", 0.98, 4.8, 0.007, 0.03, "sales@kaveri.example"),
    ("BluePeak Automation", 0.73, 24.6, 0.074, 0.21, "risk@bluepeak.example"),
]


NODE_UPDATES = {
    "demand": ("Demand planning", "at_risk", {"system": "CRM + order book", "refresh_minutes": 30, "owner_team": "S&OP"}),
    "supplier": ("Tier-1 component suppliers", "disputed", {"active_suppliers": 8, "critical_suppliers": 2, "country_count": 4}),
    "procurement": ("Procurement & approvals", "at_risk", {"open_purchase_orders": 17, "approval_threshold_inr": 500000}),
    "production": ("Control-panel assembly", "at_risk", {"lines": 3, "weekly_capacity": 640, "current_utilization": 0.91}),
    "logistics": ("Inbound & outbound logistics", "critical", {"carriers": 4, "open_shipments": 23, "expedites": 3}),
    "customer": ("Customer fulfilment", "healthy", {"active_orders": 61, "otif_target": 0.96, "priority_accounts": 7}),
}


EVIDENCE = {
    "demand": [
        ("forecast.shift", "Confirmed order book is 18% above the August consensus plan.", {"baseline_units": 4120, "confirmed_units": 4862, "variance_pct": 18.0}, 0.98, "erp"),
        ("demand.surge", "Hospital automation orders for Safety Relays rose 42% week over week.", {"sku": "SKU-002", "previous_week": 214, "current_week": 304}, 0.97, "crm"),
        ("customer.priority", "MetroCare advanced 120 control-panel deliveries by nine days.", {"customer": "MetroCare", "units": 120, "days_advanced": 9}, 0.95, "crm"),
        ("forecast.accuracy", "Thirty-day demand forecast MAPE improved to 8.7% after order-book reconciliation.", {"mape_pct": 8.7, "previous_mape_pct": 12.4}, 0.93, "analytics"),
        ("promotion.update", "Distributor promotion adds an estimated 310 Control Cable kits this month.", {"sku": "SKU-003", "incremental_units": 310}, 0.86, "partner_portal"),
        ("demand.anomaly", "An isolated 9,800-unit Sensor demand record was rejected as implausible.", {"sku": "SKU-001", "quantity": 9800, "disposition": "quarantined"}, 1.0, "anomaly_detector"),
        ("service.requirement", "Service-parts reserve increased by 35 Secure IIoT Gateways.", {"sku": "SKU-011", "reserve_units": 35}, 0.91, "service_desk"),
        ("forecast.review", "S&OP review retained the upside scenario with a 70% confidence weight.", {"scenario": "upside", "weight": 0.7}, 0.9, "manual"),
    ],
    "supplier": [
        ("supplier.delay", "Apex Industrial moved Safety Relay lead time from 12 to 17 days.", {"supplier": "Apex Industrial", "sku": "SKU-002", "old_days": 12, "new_days": 17}, 0.98, "supplier_api"),
        ("supplier.quality", "Vector Parts defect rate reached 6.1%, above the 3% control limit.", {"supplier": "Vector Parts", "defect_rate": 0.061, "limit": 0.03}, 0.96, "quality_system"),
        ("supplier.capacity", "Nova Components reserved 600 Sensor units for the next two weeks.", {"supplier": "Nova Components", "sku": "SKU-001", "reserved_units": 600}, 0.94, "supplier_api"),
        ("security.certificate", "BluePeak supplier API presented a certificate fingerprint not listed in the trust registry.", {"supplier": "BluePeak Automation", "control": "certificate_pinning", "disposition": "blocked"}, 1.0, "security_gateway"),
        ("supplier.alternate", "Orion Controls passed technical qualification for Safety Relay secondary sourcing.", {"supplier": "Orion Controls", "sku": "SKU-002", "capacity_per_week": 180}, 0.92, "quality_system"),
        ("supplier.financial", "Meridian Power price variance widened to 13% after copper surcharge notice.", {"supplier": "Meridian Power", "price_variance": 0.13}, 0.88, "procurement"),
        ("shipment.asn", "Apex ASN reports 480 Safety Relays dispatched on consignment APX-8841.", {"asn": "APX-8841", "sku": "SKU-002", "quantity": 480}, 0.93, "supplier_api"),
        ("shipment.asn", "Warehouse scan expects only 320 Safety Relays on consignment APX-8841.", {"asn": "APX-8841", "sku": "SKU-002", "quantity": 320}, 0.99, "warehouse_scan"),
    ],
    "procurement": [
        ("purchase_order.update", "Seventeen purchase orders remain open; four are inside their escalation window.", {"open": 17, "escalation_window": 4}, 0.99, "erp"),
        ("approval.required", "Expedited Safety Relay order requires manager approval before 15:00 IST.", {"sku": "SKU-002", "quantity": 420, "value_inr": 2480000}, 0.98, "workflow"),
        ("supplier.quote", "Orion offered 420 Safety Relays at an 8.5% premium with seven-day delivery.", {"supplier": "Orion Controls", "quantity": 420, "premium_pct": 8.5, "lead_time_days": 7}, 0.94, "supplier_portal"),
        ("budget.update", "Expedite reserve has INR 3.2 million available this quarter.", {"available_inr": 3200000, "quarter": "Q3"}, 0.97, "finance"),
        ("contract.control", "Dual-source clause permits a 25% emergency allocation without renegotiation.", {"emergency_allocation_pct": 25}, 0.96, "contract_repository"),
        ("purchase_order.delay", "PO-7712 for HMI panels missed supplier acknowledgement SLA by 11 hours.", {"po": "PO-7712", "sku": "SKU-007", "hours_late": 11}, 0.91, "erp"),
        ("spend.monitor", "Month-to-date component spend is 6.4% above plan, driven by expedited freight.", {"variance_pct": 6.4, "driver": "expedited_freight"}, 0.95, "finance"),
        ("approval.update", "Production manager approved alternate-source technical equivalence.", {"sku": "SKU-002", "approval": "technical_equivalence"}, 0.93, "workflow"),
    ],
    "production": [
        ("production.constraint", "Assembly Line 2 will exhaust verified Safety Relays in 2.1 operating days.", {"line": 2, "sku": "SKU-002", "cover_days": 2.1}, 0.99, "mes"),
        ("production.schedule", "Re-sequencing SKU-006 work can protect 84 priority-panel completions.", {"deferred_sku": "SKU-006", "protected_orders": 84}, 0.94, "scheduler"),
        ("production.output", "Yesterday's output was 116 panels against a plan of 128.", {"actual": 116, "plan": 128, "attainment_pct": 90.6}, 0.99, "mes"),
        ("quality.hold", "Eight panels are on hold pending relay lot traceability verification.", {"units": 8, "reason": "lot_traceability"}, 0.98, "quality_system"),
        ("maintenance.update", "Line 1 preventive maintenance completed with no overdue work orders.", {"line": 1, "overdue_work_orders": 0}, 0.97, "cmms"),
        ("capacity.update", "Weekend shift adds 96-panel capacity if staffing is confirmed by Tuesday.", {"incremental_capacity": 96, "condition": "staffing_confirmation"}, 0.88, "workforce"),
        ("material.shortage", "HMI Touch Panel allocation constrains premium-panel build after 6 September.", {"sku": "SKU-007", "constraint_date": "2026-09-06"}, 0.92, "mrp"),
        ("production.risk", "Current mix raises overtime exposure to 14% of direct labour hours.", {"overtime_exposure_pct": 14}, 0.9, "analytics"),
    ],
    "logistics": [
        ("shipment.delay", "Chennai port congestion added an estimated four days to container MSCU-441982.", {"container": "MSCU-441982", "delay_days": 4, "port": "Chennai"}, 0.97, "carrier_api"),
        ("shipment.exception", "Temperature logger on power-module shipment crossed 45C for 38 minutes.", {"shipment": "BLP-2208", "max_c": 47.2, "minutes": 38}, 0.99, "iot_sensor"),
        ("customs.update", "Secure Gateway consignment requires additional dual-use classification evidence.", {"sku": "SKU-011", "status": "document_hold"}, 0.96, "customs_broker"),
        ("carrier.capacity", "Air-freight partner can accept 420 kg on tonight's Bengaluru service.", {"capacity_kg": 420, "departure": "23:40 IST"}, 0.92, "carrier_api"),
        ("warehouse.capacity", "Finished-goods warehouse is at 78% pallet utilization.", {"utilization_pct": 78, "threshold_pct": 90}, 0.99, "wms"),
        ("shipment.received", "Nova Sensor shipment NV-5931 received complete with 600 accepted units.", {"shipment": "NV-5931", "sku": "SKU-001", "accepted_units": 600}, 0.99, "wms"),
        ("route.risk", "Flood advisory raises the Hosur road corridor risk to high for 12 hours.", {"corridor": "Hosur", "risk_window_hours": 12}, 0.9, "weather_feed"),
        ("delivery.blocked", "Priority shipment SC-1042 cannot dispatch until quality releases relay lot AR-27.", {"shipment": "SC-1042", "lot": "AR-27", "blocked_units": 48}, 0.99, "wms"),
    ],
    "customer": [
        ("service.level", "On-time-in-full performance is 96.8% for the rolling 30-day window.", {"otif_pct": 96.8, "target_pct": 96.0}, 0.99, "erp"),
        ("customer.commitment", "Five priority accounts have confirmed revised delivery windows.", {"accounts_confirmed": 5, "accounts_pending": 2}, 0.93, "crm"),
        ("order.backlog", "Backlog is 184 panels, down from 211 one week ago.", {"current": 184, "previous": 211}, 0.98, "erp"),
        ("customer.risk", "Two healthcare orders carry contractual late-delivery penalties.", {"orders": 2, "exposure_inr": 780000}, 0.97, "contract_repository"),
        ("returns.update", "Field return rate remains stable at 0.7%; no common failure mode detected.", {"return_rate_pct": 0.7, "common_mode": False}, 0.96, "service_desk"),
        ("customer.feedback", "MetroCare accepted split delivery if the first 70 panels arrive by Friday.", {"customer": "MetroCare", "first_lot": 70}, 0.95, "crm"),
        ("service.update", "No Severity-1 product incidents are open across installed sites.", {"severity_1_open": 0}, 0.99, "service_desk"),
        ("fulfilment.outlook", "Current mitigation plan preserves 94% of September committed revenue.", {"revenue_preserved_pct": 94}, 0.89, "analytics"),
    ],
}


ACTIONS = {
    "demand": [
        ("Validate the 42% Safety Relay demand surge", "Reconcile CRM orders with distributor sell-through before the 15:00 planning cut-off.", Role.ANALYST.value, "high", "Prevents an unverified demand spike from distorting procurement and production plans.", 4, "pending"),
    ],
    "supplier": [
        ("Reconcile conflicting ASN quantities", "Apex reports 480 units while the receiving scan expects 320 for the same consignment.", Role.ANALYST.value, "critical", "Restores a trusted shipment quantity before inventory is updated.", 2, "pending"),
        ("Suspend BluePeak API credentials", "The presented TLS certificate fingerprint does not match the approved supplier registry.", Role.ADMIN.value, "critical", "Contains a possible supplier-spoofing attempt without affecting approved integrations.", 1, "pending"),
        ("Qualify Orion as the Safety Relay fallback", "Technical equivalence passed and seven-day capacity is available.", Role.MANAGER.value, "high", "Reduces single-source exposure and protects 420 units of near-term demand.", 8, "approved"),
    ],
    "procurement": [
        ("Approve the 420-unit expedited relay order", "Inventory cover is below inbound lead time and emergency budget is available.", Role.MANAGER.value, "critical", "Avoids an estimated 2.6-day Line 2 stoppage and protects priority orders.", 3, "pending"),
        ("Review HMI purchase order PO-7712", "The supplier acknowledgement SLA has been exceeded by 11 hours.", Role.MANAGER.value, "normal", "Surfaces schedule risk before the 6 September material constraint.", 12, "pending"),
    ],
    "production": [
        ("Re-sequence Line 2 around relay availability", "Build relay-independent SKU-006 work while the disputed relay shipment is reconciled.", Role.ANALYST.value, "high", "Protects 84 panel completions and uses constrained labour capacity productively.", 6, "pending"),
        ("Authorize the contingency weekend shift", "Additional capacity may be needed to recover the priority healthcare backlog.", Role.MANAGER.value, "normal", "Adds up to 96 panels of recoverable weekly capacity.", 24, "rejected"),
    ],
    "logistics": [
        ("Book tonight's Bengaluru air-freight capacity", "A 420 kg slot is available while the Chennai route carries a four-day delay.", Role.MANAGER.value, "high", "Brings critical components inside the production shortage window.", 2, "pending"),
        ("Inspect temperature-exposed power modules", "Shipment BLP-2208 exceeded its temperature handling threshold for 38 minutes.", Role.ANALYST.value, "high", "Prevents suspect power modules from entering finished goods.", 5, "pending"),
    ],
}


ALERTS = [
    ("availability", "critical", "Safety Relay cover below inbound lead time", "SKU-002 has 38 units available while confirmed lead time has increased to 17 days."),
    ("integrity", "critical", "Conflicting quantities for Apex ASN APX-8841", "Supplier API reports 480 units; warehouse evidence reports 320. Inventory posting is blocked."),
    ("authentication", "critical", "Untrusted BluePeak certificate blocked", "The supplier endpoint presented a TLS fingerprint absent from the approved trust registry."),
    ("logistics", "high", "Chennai port congestion threatens critical inbound", "Container MSCU-441982 is expected four days late; expedited air capacity is available."),
    ("quality", "high", "Power modules exposed above temperature limit", "Shipment BLP-2208 exceeded 45C for 38 minutes and requires inspection."),
    ("production", "high", "Assembly Line 2 relay shortage forecast", "Verified Safety Relay inventory covers approximately 2.1 operating days."),
    ("procurement", "medium", "HMI PO acknowledgement overdue", "PO-7712 has exceeded supplier acknowledgement SLA by 11 hours."),
    ("financial", "medium", "Component spend above monthly plan", "Month-to-date component spend is 6.4% above plan due to expedited freight."),
    ("customs", "medium", "Secure Gateway consignment on document hold", "Dual-use classification evidence is required before customs release."),
    ("customer", "medium", "Healthcare orders carry late penalties", "Two priority orders have a combined INR 780,000 late-delivery exposure."),
    ("capacity", "low", "Finished-goods warehouse at 78%", "Pallet utilization remains below the 90% intervention threshold."),
    ("quality", "low", "Field return rate stable", "Rolling return rate is 0.7% with no common failure mode detected."),
]


def _upsert_products_and_sales(db) -> list[Product]:
    by_sku = {item.sku: item for item in db.scalars(select(Product)).all()}
    products: list[Product] = []
    rng = random.Random(20260831)
    start = date.today() - timedelta(days=364)
    for index, (sku, name, stock, cost, order_cost, holding, lead_time, baseline) in enumerate(PRODUCTS):
        product = by_sku.get(sku)
        if product is None:
            product = Product(
                sku=sku,
                name=name,
                current_stock=stock,
                unit_cost=cost,
                order_cost=order_cost,
                holding_cost_rate=holding,
                lead_time_days=lead_time,
            )
            db.add(product)
            db.flush()
        product.name = name
        product.current_stock = stock
        product.unit_cost = cost
        product.order_cost = order_cost
        product.holding_cost_rate = holding
        product.lead_time_days = lead_time
        existing_dates = set(db.scalars(select(SaleRecord.sold_at).where(SaleRecord.product_id == product.id)).all())
        for day in range(365):
            sold_at = start + timedelta(days=day)
            if sold_at in existing_dates:
                continue
            weekly = 0.13 * baseline * math.sin((day % 7) / 7 * math.tau)
            annual = 0.08 * baseline * math.sin(day / 365 * math.tau)
            trend = day * baseline * (0.00045 + index * 0.000012)
            campaign = baseline * 0.38 if 300 <= day <= 325 and sku in {"SKU-002", "SKU-003", "SKU-008"} else 0
            quantity = max(1, round(baseline + weekly + annual + trend + campaign + rng.gauss(0, max(1.2, baseline * 0.08))))
            db.add(SaleRecord(product_id=product.id, sold_at=sold_at, quantity=quantity))
        products.append(product)
    return products


def _upsert_suppliers(db) -> list[Supplier]:
    by_name = {item.name: item for item in db.scalars(select(Supplier)).all()}
    suppliers = []
    for name, reliability, lead_time, defect_rate, variance, contact in SUPPLIERS:
        item = by_name.get(name)
        if item is None:
            item = Supplier(name=name, encrypted_contact=encrypt_field(contact))
            db.add(item)
        item.reliability = reliability
        item.average_lead_time = lead_time
        item.defect_rate = defect_rate
        item.price_variance = variance
        suppliers.append(item)
    return suppliers


def _seed_imports(db, admin: User) -> None:
    specs = [
        ("ERP daily sales - 2026-08-29", 144, 0),
        ("Supplier ASN reconciliation - 2026-08-30", 82, 2),
        ("Distributor demand upload - 2026-08-31", 96, 3),
    ]
    for dataset_name, rows, quarantined in specs:
        digest = hashlib.sha256(f"{DATASET_VERSION}:{dataset_name}".encode()).hexdigest()
        if db.scalar(select(ImportBatch).where(ImportBatch.digest == digest)):
            continue
        batch = ImportBatch(
            dataset_name=dataset_name,
            digest=digest,
            status="quarantined" if quarantined else "accepted",
            row_count=rows,
            quarantined_count=quarantined,
            created_by=admin.id,
        )
        db.add(batch)
        db.flush()
        reasons = [
            "demand spike exceeds eight times the dataset median",
            "supplier quantity conflicts with authenticated warehouse evidence",
            "source certificate fingerprint is not trusted",
        ]
        for offset in range(quarantined):
            db.add(QuarantinedRecord(
                import_batch_id=batch.id,
                row_number=12 + offset * 17,
                payload_json=json.dumps({"synthetic": True, "record": offset + 1, "dataset": dataset_name}, sort_keys=True),
                reason=reasons[offset % len(reasons)],
            ))
        append_audit(db, "import.ingested", admin.id, {"batch_id": batch.id, "digest": digest, "accepted": rows - quarantined, "quarantined": quarantined})


def _seed_evidence(db, nodes: dict[str, SupplyChainNode], admin: User) -> dict[str, list[EvidenceRecord]]:
    now = utcnow()
    result: dict[str, list[EvidenceRecord]] = {}
    for node_key, specs in EVIDENCE.items():
        node = nodes[node_key]
        records = []
        for index, (event_type, summary, payload, confidence, source) in enumerate(specs):
            external_id = f"{DATASET_VERSION}:{node_key}:{index + 1}"
            item = db.scalar(select(EvidenceRecord).where(EvidenceRecord.external_id == external_id))
            if item is None:
                canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
                occurred_at = now - timedelta(hours=(len(specs) - index) * 4 + (len(result) * 2))
                item = EvidenceRecord(
                    node_id=node.id,
                    source_type=source,
                    external_id=external_id,
                    event_type=event_type,
                    summary=summary,
                    payload_json=canonical,
                    integrity_digest=hashlib.sha256(f"{event_type}:{summary}:{canonical}".encode()).hexdigest(),
                    confidence=confidence,
                    actor_id=admin.id if source == "manual" else None,
                    occurred_at=occurred_at,
                    received_at=occurred_at + timedelta(minutes=3),
                )
                if node_key == "supplier" and index in {6, 7}:
                    item.status = "disputed"
                    item.conflict_key = "apex:APX-8841:quantity"
                db.add(item)
            records.append(item)
        result[node_key] = records
    db.flush()
    return result


def _seed_guidance_and_actions(db, nodes: dict[str, SupplyChainNode], evidence: dict[str, list[EvidenceRecord]], manager: User) -> None:
    now = utcnow()
    for node_key, node in nodes.items():
        rows = sorted(evidence[node_key], key=lambda item: item.occurred_at, reverse=True)[:20]
        node_payload = {
            "id": node.id,
            "key": node.key,
            "name": node.name,
            "stage_type": node.stage_type,
            "owner_role": node.owner_role,
            "position": {"x": node.position_x, "y": node.position_y},
            "status": node.status,
            "metadata": json.loads(node.metadata_json),
            "updated_at": node.updated_at,
        }
        evidence_payload = [
            {
                "id": item.id,
                "node_id": item.node_id,
                "source_type": item.source_type,
                "external_id": item.external_id,
                "event_type": item.event_type,
                "summary": item.summary,
                "payload": json.loads(item.payload_json),
                "integrity_digest": item.integrity_digest,
                "confidence": item.confidence,
                "status": item.status,
                "conflict_key": item.conflict_key,
                "actor_id": item.actor_id,
                "occurred_at": item.occurred_at,
                "received_at": item.received_at,
            }
            for item in rows
        ]
        digest = context_digest(node_payload, evidence_payload)
        run = db.scalar(select(GuidanceRun).where(GuidanceRun.node_id == node.id, GuidanceRun.context_digest == digest))
        if run is None:
            disputed = [item.id for item in rows if item.status == "disputed"]
            risk = node.status != "healthy"
            run = GuidanceRun(
                node_id=node.id,
                context_digest=digest,
                provider="deterministic",
                status_summary=(f"{node.name} has conflicting trusted-source evidence." if disputed else f"{node.name} requires intervention." if risk else f"{node.name} is operating within its monitored range."),
                rationale=("Conflicting records are preserved and dependent decisions are blocked pending human reconciliation." if disputed else rows[0].summary if rows else "No unresolved exception is present."),
                evidence_ids_json=json.dumps(disputed or [item.id for item in rows[:3]]),
                confidence=1.0 if disputed else 0.94 if rows else 0.65,
                no_action_required=not risk,
                next_check_at=now + timedelta(hours=2 if disputed else 4 if risk else 24),
                created_at=now - timedelta(minutes=20),
            )
            db.add(run)
            db.flush()
        for index, (title, reason, owner, urgency, impact, due_hours, status) in enumerate(ACTIONS.get(node_key, [])):
            if db.scalar(select(ActionProposal).where(ActionProposal.node_id == node.id, ActionProposal.title == title)):
                continue
            action = ActionProposal(
                node_id=node.id,
                guidance_run_id=run.id,
                title=title,
                reason=reason,
                owner_role=owner,
                urgency=urgency,
                expected_impact=impact,
                due_at=now + timedelta(hours=due_hours),
                status=status,
                created_at=now - timedelta(minutes=15 - index),
            )
            if status != "pending":
                action.decided_by = manager.id
                action.decision_note = "Synthetic prior decision included to demonstrate the governed approval history."
            db.add(action)


def _seed_forecasts_and_recommendations(db, products: list[Product], suppliers: list[Supplier], manager: User) -> None:
    now = utcnow()
    best_risk = min(supplier_risk(item.reliability, item.average_lead_time, item.defect_rate, item.price_variance) for item in suppliers)
    for index, product in enumerate(products):
        quantities = [float(value) for value in db.scalars(select(SaleRecord.quantity).where(SaleRecord.product_id == product.id).order_by(SaleRecord.sold_at)).all()]
        recent = quantities[-30:]
        daily = round(statistics.mean(recent), 2)
        forecast = db.scalar(select(Forecast).where(Forecast.product_id == product.id).order_by(Forecast.created_at.desc()).limit(1))
        if forecast is None:
            forecast = Forecast(
                product_id=product.id,
                horizon_days=14,
                daily_demand=daily,
                mae=round(1.35 + index * 0.17, 3),
                rmse=round(1.82 + index * 0.21, 3),
                mape=round(5.8 + index * 0.48, 3),
                baseline_mae=round(2.65 + index * 0.24, 3),
                model_name="XGBoost",
                explanation_json=json.dumps([
                    {"feature": "lag_7", "importance": 0.38},
                    {"feature": "rolling_7", "importance": 0.27},
                    {"feature": "lag_1", "importance": 0.19},
                    {"feature": "day_of_week", "importance": 0.1},
                    {"feature": "month", "importance": 0.06},
                ]),
                created_at=now - timedelta(hours=12 - index),
            )
            db.add(forecast)
            db.flush()
        if db.scalar(select(Recommendation).where(Recommendation.product_id == product.id)):
            continue
        policy = inventory_policy(
            daily,
            statistics.stdev(recent),
            product.lead_time_days,
            statistics.mean(quantities[-90:]) * 365,
            product.order_cost,
            product.unit_cost,
            product.holding_cost_rate,
            product.current_stock,
        )
        status = "approved" if index in {0, 5} else "rejected" if index == 8 else "pending"
        recommendation = Recommendation(
            product_id=product.id,
            forecast_id=forecast.id,
            supplier_risk=round(best_risk + (index % 4) * 4.7, 1),
            status=status,
            created_at=now - timedelta(hours=11 - index),
            **policy,
        )
        if status != "pending":
            recommendation.decided_by = manager.id
            recommendation.decision_note = "Approved for routine replenishment." if status == "approved" else "Rejected because verified stock is already in transit."
        db.add(recommendation)


def load_rich_demo_data() -> dict[str, int | str]:
    seed_database()
    with SessionLocal() as db:
        if db.scalar(select(AuditEvent).where(AuditEvent.event_type == MARKER_EVENT)):
            return {"status": "already_loaded", "version": DATASET_VERSION}

        admin = db.scalar(select(User).where(User.role == Role.ADMIN.value))
        manager = db.scalar(select(User).where(User.role == Role.MANAGER.value))
        if admin is None or manager is None:
            raise RuntimeError("Demo users are missing")

        profile = db.scalar(select(OrganizationProfile).limit(1))
        if profile:
            profile.name = "Sentinel Industrial Systems"
            profile.industry = "Industrial automation and safety control panels"
            profile.description = "A synthetic Bengaluru manufacturer coordinating tier-1 electronics suppliers, governed procurement, three assembly lines, logistics partners, and priority healthcare customers."
            profile.objectives_json = json.dumps(["Protect priority customer deliveries", "Prevent component stockouts", "Detect poisoned or conflicting operational data", "Keep material actions human-approved"])
            profile.constraints_json = json.dumps(["No autonomous purchase orders", "Untrusted supplier data must be quarantined", "Critical components require lot traceability", "Synthetic classroom data only"])
            profile.updated_by = admin.id

        products = _upsert_products_and_sales(db)
        suppliers = _upsert_suppliers(db)
        _seed_imports(db, admin)

        default_chain = db.scalar(select(SupplyChain).where(SupplyChain.key == DEFAULT_CHAIN_KEY).order_by(SupplyChain.id))
        if default_chain is None:
            default_chain = SupplyChain(key=DEFAULT_CHAIN_KEY, name=DEFAULT_CHAIN_NAME, created_by=admin.id)
            db.add(default_chain)
            db.flush()
        nodes = {item.key: item for item in db.scalars(select(SupplyChainNode).where(SupplyChainNode.chain_id == default_chain.id)).all()}
        for key, (name, status, metadata) in NODE_UPDATES.items():
            node = nodes[key]
            node.name = name
            node.status = status
            node.metadata_json = json.dumps(metadata, sort_keys=True)
        for edge in db.scalars(select(SupplyChainEdge)).all():
            source = next((node for node in nodes.values() if node.id == edge.source_node_id), None)
            target = next((node for node in nodes.values() if node.id == edge.target_node_id), None)
            edge.status = "at_risk" if source and target and (source.status != "healthy" or target.status != "healthy") else "healthy"
        db.flush()

        evidence = _seed_evidence(db, nodes, admin)
        _seed_guidance_and_actions(db, nodes, evidence, manager)
        _seed_forecasts_and_recommendations(db, products, suppliers, manager)

        for index, (category, severity, title, detail) in enumerate(ALERTS):
            if db.scalar(select(Alert).where(Alert.title == title)):
                continue
            db.add(Alert(category=category, severity=severity, title=title, detail=detail, status="open", created_at=utcnow() - timedelta(hours=index * 3)))

        append_audit(db, "demo.scenario.activated", admin.id, {"scenario": "supplier disruption and trusted-evidence response", "synthetic": True})
        append_audit(db, "security.certificate_blocked", admin.id, {"supplier": "BluePeak Automation", "control": "certificate_pinning", "synthetic": True})
        append_audit(db, "evidence.conflict_detected", admin.id, {"external_reference": "APX-8841", "decision_state": "blocked", "synthetic": True})
        append_audit(db, MARKER_EVENT, admin.id, {"version": DATASET_VERSION, "products": len(products), "sales_days": 365, "evidence": sum(len(items) for items in evidence.values()), "synthetic": True})
        db.commit()

        return {
            "status": "loaded",
            "version": DATASET_VERSION,
            "products": len(products),
            "sales_records": len(products) * 365,
            "suppliers": len(suppliers),
            "evidence_records": sum(len(items) for items in evidence.values()),
        }


if __name__ == "__main__":
    print(json.dumps(load_rich_demo_data(), sort_keys=True))
