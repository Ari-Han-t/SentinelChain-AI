# SentinelChain AI: Secure Supply Chain Control Tower

## Summary

Build a security-first supply-chain platform for inventory managers and procurement analysts. It converts sales, inventory, and supplier data into demand forecasts, reorder recommendations, supplier-risk scores, and security alerts.

The central demo:

1. Import a valid dataset.
2. Forecast demand and generate reorder recommendations.
3. Simulate stock manipulation, demand poisoning, or supplier spoofing.
4. Detect and quarantine compromised records.
5. Show the unsafe decision that was prevented.
6. Preserve the incident in a tamper-evident audit trail.
7. Require human approval before creating a simulated purchase order.

## Product and Architecture

### Core capabilities

- Control-tower dashboard showing stock health, predicted demand, supplier risk, active alerts, and pending approvals.
- CSV ingestion for products, sales, inventory, suppliers, and purchase orders.
- XGBoost demand forecasting using lag, rolling-average, seasonal, and calendar features.
- Forecast evaluation against a moving-average baseline using MAE, RMSE, and MAPE.
- Explainable predictions using SHAP feature contributions.
- Reorder point, safety-stock, and EOQ calculations.
- Supplier scoring using delivery reliability, lead time, defect rate, and price variance.
- Human approval workflow for simulated purchase orders.
- Admin-only attack simulator for presentation and testing.

### Information-security layer

- HMAC-SHA256 verification for imported dataset manifests.
- Schema validation and business-rule validation before ingestion.
- Isolation Forest and rule-based detection for suspicious data changes.
- Quarantine area preventing compromised records from reaching forecasting.
- Role-based access: Administrator, Inventory Analyst, Procurement Manager, and Auditor.
- Argon2 password hashing and short-lived JWT authentication.
- AES-GCM encryption for sensitive supplier information.
- Tamper-evident audit events chained using the previous event's SHA-256 hash.
- Rate limiting, restricted CORS, parameterized database access, secret management, and HTTPS in production.
- Security alerts mapped to confidentiality, integrity, availability, authentication, and accountability.

### Technical stack

- Frontend: React, TypeScript, Vite, Tailwind CSS, Recharts, TanStack Query.
- Backend: Python, FastAPI, Pydantic, SQLAlchemy, Alembic.
- Analytics: Pandas, NumPy, scikit-learn, XGBoost, SHAP.
- Database: PostgreSQL.
- Testing: Pytest, Vitest, React Testing Library, Playwright.
- Local deployment: Docker Compose.
- Cloud deployment: Vercel frontend, Render backend and PostgreSQL.
- CI/CD: GitHub Actions for tests, builds, dependency scanning, and deployment.

### Main entities and interfaces

Entities include users, products, sales records, inventory snapshots, suppliers, purchase orders, forecasts, recommendations, alerts, quarantined records, imports, and audit events.

Primary API groups:

- `/auth`: login and session handling.
- `/imports`: validate, verify, preview, and ingest datasets.
- `/dashboard`: KPIs and inventory health.
- `/forecasts`: train, evaluate, explain, and retrieve forecasts.
- `/recommendations`: generate, approve, or reject reorder proposals.
- `/suppliers`: scorecards and risk details.
- `/alerts`: operational and security incidents.
- `/audit`: verified audit history.
- `/demo/attacks`: controlled attacks in demo environments only.

## Delivery Plan

1. Build authentication, database schema, CSV ingestion, and audit logging.
2. Implement forecasting, evaluation, reorder calculations, and supplier scoring.
3. Build the dashboard, product detail, supplier-risk, alerts, and approval screens.
4. Add integrity verification, anomaly detection, quarantine, and the demo attack utility.
5. Add Docker, cloud deployment, automated tests, seeded datasets, and a scripted presentation.
6. Use synthetic retail data and clearly label every generated result; never present synthetic metrics as real-world performance.

## Test and Acceptance Plan

- Valid imports produce forecasts and recommendations.
- Malformed or unsigned imports are rejected.
- Modified signed data fails integrity verification.
- Statistical poisoning is detected or flagged for review.
- Quarantined data never influences forecasts.
- Unauthorized roles cannot approve orders, run attacks, or inspect protected audit data.
- Editing an audit event breaks chain verification.
- Forecast performance is displayed against the baseline.
- Every recommendation explains forecast, lead time, safety stock, and supplier risk.
- Docker launches the complete system with one command.
- The cloud demo reproduces the normal-operation and attack-recovery flows.
- The presentation demo completes in under seven minutes.

## Prompt: 12-Slide Presentation Deck

```text
Create an editable, university-level 12-slide PowerPoint presentation titled:

"SentinelChain AI: A Secure Supply Chain and Inventory Intelligence Control Tower"

Audience:
Information Security course faculty and student evaluators.

Purpose:
Explain the product idea, demonstrate its information-security relevance, describe its AI and system architecture, and present a convincing implementation and evaluation plan.

Product:
SentinelChain AI is a secure web-based control tower for inventory managers and procurement analysts. It imports historical sales, inventory, supplier, and purchase-order data; forecasts product demand; calculates safety stock, reorder points, and EOQ; evaluates supplier risk; and produces human-approved reorder recommendations.

Its distinguishing feature is protection against corrupted operational data. It verifies dataset integrity with HMAC-SHA256, detects suspicious changes using business rules and Isolation Forest, quarantines compromised records, uses role-based access control, encrypts sensitive supplier information, and records actions in a hash-chained tamper-evident audit log. An admin-only demonstration utility can simulate demand poisoning, inventory manipulation, and supplier spoofing. The presentation must show how an attack could create an unsafe reorder recommendation and how SentinelChain prevents it.

Create these slides:

1. Title
   - Project name, subtitle, course, student name, registration number.
   - One-sentence value proposition.

2. Problem
   - Stockouts, excess inventory, supplier delays, poor visibility.
   - Explain why corrupted or manipulated data makes automated decisions dangerous.

3. Proposed Solution
   - Present SentinelChain AI and its primary users.
   - Show the normal workflow from data import to approved reorder decision.

4. Major Product Features
   - Demand forecasting, inventory optimization, supplier scorecards, alerts, approvals, audit history.

5. Information-Security Threat Model
   - Assets, actors, attack surfaces, and threats.
   - Include demand poisoning, stock manipulation, supplier spoofing, unauthorized approvals, and audit-log tampering.
   - Map controls to confidentiality, integrity, availability, authentication, authorization, and accountability.

6. System Architecture
   - Diagram: React frontend -> FastAPI API -> security/validation layer -> analytics engine -> PostgreSQL.
   - Include deployment, authentication, encryption, quarantine, and audit components.

7. AI and Optimization Pipeline
   - CSV validation, feature engineering, XGBoost forecast, baseline comparison, SHAP explanation, reorder calculations.
   - Include MAE, RMSE, and MAPE as evaluation metrics.

8. Security Architecture
   - HMAC-SHA256 import verification.
   - Argon2 passwords, JWT sessions, RBAC, AES-GCM sensitive-field encryption.
   - Anomaly detection, quarantine, hash-chained audit events, HTTPS, and rate limiting.

9. Attack-and-Recovery Demonstration
   - Visual sequence: valid data -> attack injected -> detection -> quarantine -> safe recalculation -> auditor evidence.
   - Contrast unsafe and protected recommendations.

10. User Interface
    - Show conceptual mockups for the control-tower dashboard, product forecast, supplier risk, alert investigation, approval screen, and audit trail.
    - Use realistic sample values clearly marked as synthetic.

11. Testing, Results, and Success Criteria
    - Functional, security, ML, authorization, integrity, and end-to-end tests.
    - Do not invent completed experimental results. Use labelled placeholders or "target" values until measured.

12. Conclusion and Future Work
    - Restate academic and operational value.
    - Future work: ERP integration, streaming data, federated learning, advanced model monitoring, and real purchase-order integrations.

Design requirements:
- Professional dark navy, white, and restrained cyan/red palette.
- Prefer diagrams, charts, and short statements over paragraphs.
- Use consistent icons and typography.
- Add concise speaker notes to every slide.
- Include a final references area using the three papers cited in the source proposal.
- Clearly label synthetic data, target metrics, and conceptual mockups.
- Do not claim that the system is fully autonomous or production-certified.
```

## Prompt: Eight-Page Product Description Document

```text
Write an approximately eight-page, submission-ready product description document titled:

"SentinelChain AI: Secure Supply Chain and Inventory Intelligence Platform"

Audience:
Information Security course faculty. Use formal but readable academic language.

Objective:
Describe a feasible security-first supply-chain control tower, its users, functionality, AI methods, architecture, security design, evaluation, deployment, limitations, and future work. The document must connect every technical choice to either a business decision or an information-security risk.

Product definition:
SentinelChain AI imports historical sales, inventory, supplier, and purchase-order datasets. It forecasts SKU demand with XGBoost, compares results with a moving-average baseline, explains predictions with SHAP, calculates safety stock, reorder points, and EOQ, scores supplier risk, and produces recommendations requiring human approval.

The system must distrust incoming operational data. It uses HMAC-SHA256 manifests, schema and business-rule validation, Isolation Forest anomaly detection, quarantine, role-based access control, Argon2 password hashing, JWT authentication, AES-GCM sensitive-field encryption, HTTPS, rate limiting, and a SHA-256 hash-chained audit log. A demo-only admin utility simulates demand poisoning, inventory manipulation, and supplier spoofing to demonstrate detection and recovery.

Use this structure:

1. Executive Summary
2. Background and Problem Statement
3. Target Users and Stakeholders
4. Product Objectives and Success Criteria
5. Functional Requirements
6. End-to-End User Workflow
7. AI Forecasting and Inventory-Optimization Methodology
8. Supplier-Risk Methodology
9. Threat Model
   - Assets
   - Threat actors
   - Trust boundaries
   - Attack surfaces
   - STRIDE-based threat table
10. Security Controls
    - Authentication and authorization
    - Data integrity
    - Encryption
    - Anomaly detection and quarantine
    - Auditability
    - API and deployment security
11. System Architecture and Data Flow
12. Database Entities and API Groups
13. Technology Stack and Justification
14. User Interface Description
15. Attack-and-Recovery Demonstration Scenario
16. Testing and Evaluation Plan
17. Deployment Plan
18. Ethical Considerations and Limitations
19. Future Enhancements
20. Conclusion
21. References

Required tables and diagrams:
- Functional and non-functional requirements table.
- User-role permissions matrix.
- STRIDE threat-model table.
- Security-control mapping table.
- Technology-stack table.
- System architecture diagram.
- Data-flow diagram showing validation, quarantine, analytics, and approval.
- Attack-and-recovery sequence diagram.
- Testing and acceptance-criteria matrix.

Writing rules:
- Clearly distinguish implemented features, planned features, and future work.
- Label all sample data and proposed results as synthetic or targets.
- Do not fabricate accuracy, performance, security, or business results.
- Explain formulas for safety stock, reorder point, and EOQ.
- Define MAE, RMSE, and MAPE and explain why a baseline model is required.
- Explain why human approval remains mandatory.
- Include privacy, model drift, false-positive, compromised-key, and insider-threat limitations.
- Use IEEE-style numbered references.
- Incorporate the three literature sources from the original proposal.
- Ensure terminology, architecture, roles, and claims match the presentation deck.
```

## Assumptions

- Target delivery is the output quality of a 4-6 week project completed within 1-3 weeks.
- No IoT hardware or real ERP integration is included.
- The project uses synthetic retail data.
- Both Docker-based local execution and a cloud demonstration are required.
- The attack simulator is a gated demonstration/testing facility, not an exposed production feature.

## Engineering Review Amendments

The implementation keeps the complete demonstration path while narrowing operational claims. PostgreSQL remains the deployment database, with SQLite used only for fast local tests. The backend is a modular FastAPI service rather than separate microservices so authentication, import validation, analytics, approvals, and audit writes share one transaction boundary.

### Data and decision flow

```text
signed CSV -> HMAC check -> schema/business rules -> anomaly detector
                                         | valid             | suspicious
                                         v                   v
                                  verified sales        quarantine + alert
                                         |
                              forecast + baseline + SHAP
                                         |
                        safety stock + reorder point + EOQ
                                         |
                             pending recommendation
                                         |
                         manager approves or rejects
                                         |
                         hash-chained audit evidence
```

### Review decisions folded into implementation

- Production refuses weak secrets and refuses to expose the attack simulator.
- Imports are content-digested and idempotent; signed but anomalous rows are quarantined before persistence to the forecasting dataset.
- Forecast results include MAE, RMSE, MAPE, the moving-average baseline, and native XGBoost TreeSHAP contributions.
- Approval uses an expected pending state so stale or repeated decisions cannot overwrite a prior decision.
- PostgreSQL schema creation is versioned with Alembic; SQLite remains a local test convenience.
- CI verifies backend behavior, frontend behavior/build, and high-severity dependency findings.

### Test coverage map

```text
Authentication -> valid login / invalid login / missing token / expired-invalid token
RBAC           -> analyst import+forecast / manager decision / auditor chain / admin attack
Import         -> valid signature / modified content / bad schema / duplicate / anomaly / unknown SKU
Analytics      -> XGBoost forecast / baseline metrics / SHAP output / inventory formulas
Approval       -> pending -> approved|rejected / repeated stale decision -> conflict
Audit          -> valid chain / edited payload -> broken chain location
UI             -> login success / recoverable login error / production build
E2E            -> admin login -> attack lab -> blocked attack comparison
```

### Failure modes covered

| Failure | Handling | User-visible result | Test |
|---|---|---|---|
| Modified signed data | Constant-time HMAC rejection | Signature mismatch | Backend test |
| Missing or malformed columns | Typed validation failure | Required-column error | Backend test |
| Poisoned demand row | Quarantine before sales insert | Security alert and evidence | Backend test |
| Unauthorized action | Route-level role dependency | HTTP 403 | Backend test |
| Repeated approval | Conditional state update | HTTP 409 conflict | Backend test |
| Audit record edit | Full chain recalculation | Broken sequence reported | Backend test |
| API/login failure | Error state retained in UI | Recoverable error banner | Frontend test |

### What already existed

- The source plan and course proposal defined the problem, threat model, stack, and acceptance criteria.
- No application code, database schema, deployment workflow, or tests existed in the target repository.

### NOT in scope

- Real ERP, payment, or purchase-order integration: the project intentionally creates simulated orders only.
- IoT devices and streaming ingestion: batch CSV proves the trust-boundary design without adding unrelated infrastructure.
- Production certification: controls are demonstrable, but operational certification requires an external review and production evidence.
- Claims about real-world model accuracy: all bundled data and measured results are synthetic.
- Multi-region scaling: a shared rate limiter and externally anchored audit roots are documented follow-up hardening work.

### Implementation Tasks

- [x] **T1 (P1)** Build authentication, role enforcement, protected configuration, and persistence.
- [x] **T2 (P1)** Build signed import validation, anomaly detection, and quarantine isolation.
- [x] **T3 (P1)** Build forecasting, baseline evaluation, TreeSHAP explanation, and inventory policy.
- [x] **T4 (P1)** Build human approval, attack simulation, alerts, and tamper-evident audit verification.
- [x] **T5 (P2)** Build the responsive React control tower and automated UI tests.
- [x] **T6 (P2)** Add Docker, Alembic, cloud manifests, CI, seeded data, and operator documentation.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | Not run | Not required for implementation |
| Codex Review | `/codex review` | Independent second opinion | 0 | Not run | Not required for implementation |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | Clear | 6 issues folded into implementation, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | Not run | UI verified through build and component tests |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | Not run | Docker and local workflows documented |

**VERDICT:** ENG CLEARED - ready to ship.

NO UNRESOLVED DECISIONS
