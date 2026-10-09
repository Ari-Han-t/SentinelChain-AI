# Classroom demo: present SentinelChain in 6-8 minutes

This walkthrough gives you a clear story, visible proof, and short explanations you can say aloud.

## Before class

1. Start the stack:

   ```powershell
   docker compose up -d
   ```

2. Verify it:

   ```powershell
   docker compose ps
   ```

   The database should say `healthy`; the API and web containers should say `Up`.

3. Open <http://localhost:5173> and keep <http://localhost:8000/docs> in a second tab.

4. Log in as the administrator:

   - Email: `admin@sentinelchain.local`
   - Password: `demo1234`

These credentials are only for the local synthetic demo.

## Your opening, about 30 seconds

Say:

> Supply chains make decisions using data from systems and outside companies. If that data is late, contradictory, or malicious, a normal dashboard can produce a confident but unsafe recommendation. SentinelChain combines operational monitoring with information-security controls. It shows where risk exists, cites the evidence, proposes the next action, requires human approval, and records the decision in a tamper-evident ledger.

## Part 1: Control tower, about 90 seconds

Show the **Control tower** page.

Point out:

- Six connected stages represent demand, suppliers, procurement, production, logistics, and customers.
- Five stages currently have an exception. This is a prepared incident scenario, not random red data.
- Each node has an owner role and a pending-action count.
- The graph communicates downstream impact: a supplier problem can affect procurement, production, logistics, and customers.

Say:

> This is not only an inventory dashboard. It is an operating model that connects evidence, risk, ownership, and decisions.

## Part 2: Conflicting supplier evidence, about 2 minutes

Click **Tier-1 component suppliers**.

In the inspector, show:

- The node is marked **disputed**.
- Apex reports 480 Safety Relays on shipment APX-8841.
- The warehouse expects only 320 for the same shipment.
- BluePeak's untrusted certificate was blocked.
- Guidance cites evidence and proposes reconciliation rather than silently selecting one quantity.

Say:

> The important security choice is preservation. The system does not overwrite one report with another. It keeps both, marks the state disputed, and blocks dependent decisions until a person resolves the conflict.

## Part 3: Human approval, about 90 seconds

Open **Action queue**.

Pick one pending action, such as:

- Reconcile conflicting ASN quantities.
- Approve the 420-unit expedited relay order.
- Book tonight's Bengaluru air-freight capacity.
- Inspect temperature-exposed power modules.

Explain the reason and expected impact, then approve or reject one action.

Say:

> The system recommends; it does not execute. Only the administrator or procurement manager can decide. The API also checks that the action is still pending, so a stale browser cannot overwrite a decision already made by someone else.

## Part 4: Audit evidence, about 60 seconds

Open **Evidence**.

Show the **Chain intact** indicator and recent events.

Say:

> Every audit record stores the hash of the previous record. If an old payload is edited, verification fails at that sequence. This detects tampering, although a production system should also anchor hash checkpoints outside the database to detect deletion by a database administrator.

## Part 5: Attack simulation, about 60 seconds

Open **Settings**, then choose one integrity drill:

- Demand poisoning
- Stock manipulation
- Supplier spoofing

Say:

> This drill injects a synthetic malicious input. SentinelChain shows the unsafe decision that raw data could cause, then shows the protected decision after validation and quarantine. The attack route is administrator-only and disabled in production mode.

## Optional API proof, about 30 seconds

Open <http://localhost:8000/docs>.

Say:

> FastAPI generates this interactive contract from the backend. It exposes authenticated endpoints for evidence, guidance, forecasts, recommendations, approvals, alerts, and audit verification.

## Your conclusion, about 30 seconds

Say:

> SentinelChain's main contribution is combining supply-chain intelligence with trust boundaries. It treats external data and AI output as inputs to verify, not commands to obey. The result is explainable guidance, least-privilege decisions, quarantine of suspicious data, and a verifiable history.

## Likely teacher questions

### Where is AI used?

Demand forecasting uses XGBoost with lag and calendar features. Guidance can use Azure AI Foundry, but its output is advisory and schema-validated. When Foundry is unavailable, deterministic guidance keeps the system operational.

### How is malicious data detected?

Imports pass HMAC verification, schema checks, business rules, and Isolation Forest anomaly detection. Suspicious rows go to quarantine and never enter trusted sales history.

### Why not let AI place the order?

AI can be wrong, manipulated, or missing business context. SentinelChain keeps material actions pending for a role-authorized person and records the decision.

### Is blockchain used?

No. The audit log is a SHA-256 hash chain inside the database. It detects edits to recorded events. It is simpler than blockchain, but external anchoring would be needed for stronger protection against privileged deletion.

### Is the data real?

No. The data is deterministic and synthetic: 12 products, 365 daily sales observations per product, 8 suppliers, and a prepared disruption scenario.

### What would you add for production?

A real ERP connector, asymmetric supplier signatures, Redis-backed rate limiting, secret management, external audit-hash anchoring, monitoring, drift detection, and a formal human review process for quarantined records.

## Troubleshooting

If the page does not load:

```powershell
docker compose ps
docker compose logs --tail 100 api web db
```

If the database volume was reset, reload the rich scenario:

```powershell
docker compose build api
docker compose run --rm api python -m app.demo_data
docker compose up -d api
```

If port 5173 or 8000 is already in use, stop the conflicting local process or change the left side of the relevant port mapping in `docker-compose.yml`.

## Related

- [Project overview](PROJECT_OVERVIEW.md)
- [Technical reference](TECHNICAL_REFERENCE.md)
- [PPT generation prompt](PPT_PROMPT.md)

