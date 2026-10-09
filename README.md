# SentinelChain AI

SentinelChain AI is a security-first, graph-based supply-chain control tower. It models each operational stage and handoff, accepts authenticated system events or structured human updates, explains current risk, recommends the next safe action, and keeps a tamper-evident record of every sensitive decision.

> All included data and displayed metrics are synthetic. The application is an academic demonstration, not a production-certified procurement system.

## What the demo proves

1. An analyst works from signed, schema-checked sales data.
2. The forecasting service compares an XGBoost model against a moving-average baseline.
3. Inventory policy explains safety stock, reorder point, EOQ, and the final order quantity.
4. An administrator injects demand poisoning, stock manipulation, or supplier spoofing.
5. SentinelChain blocks the input before it reaches forecasting and contrasts the unsafe order with the protected decision.
6. A procurement manager must approve any simulated purchase order.
7. An auditor can verify the complete hash chain.

The primary workspace is an interactive supply-chain topology. Selecting a stage shows its evidence, provenance, confidence, current guidance, downstream impact, and any human approval required. Healthy stages explicitly report when no action is needed and when they will be checked again.

## Multiple supply chains

The demo ships one seeded chain ("Sentinel Industrial Demo"), but the system is multi-chain:

- Administrators can create, rename, archive, and restore any number of supply chains from the **Supply chains** view, and switch between them with the control-tower chain selector.
- Within a chain, administrators build the graph one stage at a time: **Add stage** creates an individual node (key, name, stage type, owner role, canvas position), **Connect stages** links two nodes into a handoff, and **Handoffs** lists every connection for relabelling or deletion. Stages can be edited, dragged into position, or soft-deactivated (hidden but preserved for audit history); nodes are unique per chain, not globally.
- Every role sees every chain, but actions are role-scoped and enforced server-side from `GET /auth/permissions`: evidence submission (analyst, manager, admin), decisions (admin, manager), escalation (admin, manager), stage verification (auditor, admin), and chain/node/edge management (admin only). The UI only renders controls the signed-in role may use.
- New evidence on a stage clears its verification stamp, and auditors re-verify it explicitly (`POST /nodes/{id}/verify`).

## Azure AI Foundry guidance

Copy the Foundry variables from `.env.example` into `backend/.env`, then provide the Foundry `/openai/v1/responses` endpoint, API key, and deployment name. Calls use the OpenAI-compatible Responses API and happen only in the backend. When Foundry is disabled or unavailable, deterministic monitoring continues and the UI identifies the guidance provider.

The model is advisory: evidence is treated as untrusted data, responses are schema-validated, cited evidence IDs must exist, and suggested actions remain pending until an authorized user approves or rejects them. New evidence triggers guidance immediately; a background monitor refreshes guidance after its next-check time.

Customer systems should send normalized events to `POST /events` using an authenticated analyst or administrator account. Operators can add structured manual updates from a selected graph node. Conflicting reports are preserved, marked disputed, and block dependent actions instead of silently overwriting one another.

## Architecture

```text
Browser (React + TypeScript)
        |
        | short-lived JWT + role checks
        v
FastAPI API ---------------------------------------------------+
        |                                                     |
        +--> HMAC + schema + rules + Isolation Forest         |
        |        | accepted                 | suspicious       |
        |        v                          v                  |
        |   verified sales             quarantine + alert     |
        |        |                                             |
        +--> XGBoost -> baseline metrics -> inventory policy   |
        |                                      |               |
        +--> supplier risk --------------------+               |
        |                                      v               |
        |                              pending recommendation   |
        |                                      |               |
        |                              human approve/reject     |
        |                                                     |
        +--> SHA-256 audit chain <-----------------------------+
        |
        v
PostgreSQL (Docker/Render) or SQLite (fast local development)
```

Sensitive supplier contact fields are encrypted with AES-GCM. Passwords use Argon2. CORS is allow-listed, requests are rate-limited, demo attack routes are administrator-only and are rejected when `DEMO_MODE=false`, and all SQL access uses SQLAlchemy parameters.

## Run with Docker

```bash
docker compose up --build
```

Open [http://localhost:5173](http://localhost:5173). The API and interactive documentation are at [http://localhost:8000/docs](http://localhost:8000/docs).

## Run locally

Backend:

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Copy `.env.example` to `.env` before changing defaults. Production startup rejects short development secrets and refuses to run while the attack simulator is enabled.

## Demo accounts

All seeded users use password `demo1234`.

| Role | Email | Key permissions |
|---|---|---|
| Administrator | `admin@sentinelchain.local` | Full demo, attacks, audit |
| Inventory Analyst | `analyst@sentinelchain.local` | Imports, forecasts, recommendations |
| Procurement Manager | `manager@sentinelchain.local` | Approve or reject recommendations |
| Auditor | `auditor@sentinelchain.local` | Read and verify audit history |

## Signed imports

Sales CSVs require `sku,date,quantity`. Generate a development signature with:

```bash
cd backend
python -m app.sign_csv ../data/demo-sales.csv
```

Send the file text and returned signature to `POST /imports/preview`, then `POST /imports`. A byte-level modification changes the HMAC and is rejected. Validly signed but suspicious rows are placed in `quarantined_records`; they are never inserted into `sales_records` and cannot influence a forecast.

## Forecasting and inventory formulas

The forecasting feature set uses one-day and seven-day lags, the prior seven-day rolling mean, day of week, and month. Holdout predictions report:

- MAE: mean absolute forecast error.
- RMSE: root mean squared error, which penalizes large misses more strongly.
- MAPE: mean absolute percentage error over non-zero actuals.
- Baseline MAE: a seven-day moving-average forecast. This prevents a complex model from being presented as useful when a simple baseline is better.

Inventory calculations are:

- `Safety stock = service factor × demand standard deviation × sqrt(lead time)`
- `Reorder point = expected daily demand × lead time + safety stock`
- `EOQ = sqrt(2 × annual demand × order cost / annual holding cost)`

The recommendation remains pending until an authorized human approves or rejects it. Approval uses an expected-state update, so stale or repeated decisions return a conflict instead of overwriting history.

## Tests

```bash
cd backend && pytest -q
cd frontend && npm test -- --run
cd frontend && npm run build
```

The backend suite covers authentication, role boundaries, multi-chain and node administration, permission enforcement, evidence, HMAC tamper detection, AES-GCM behavior, quarantine isolation, duplicate imports, forecasting, approval conflicts, attack containment, and audit-chain tampering. The frontend suite covers login success, recoverable authentication failure, and role-gated navigation. A Playwright scenario exercises the full attack demonstration plus an admin flow that creates a chain, adds individual stages, and links them into a handoff.

## Deployment

- `docker-compose.yml` runs the full local stack with PostgreSQL.
- `render.yaml` defines the API and managed PostgreSQL service. Set the secret `BOOTSTRAP_ADMIN_PASSWORD`, its matching email, and `CORS_ORIGINS` before first deploy; keep `DEMO_MODE=false` for any production-labelled environment. Bootstrap is idempotent and never replaces an existing password.
- `frontend/vercel.json` supports Vercel SPA routing. Set `VITE_API_URL` during the Vercel build.
- GitHub Actions runs backend tests, frontend tests/build, and a high-severity dependency audit.

## Known limitations

- The included rate limiter is process-local. A scaled deployment should use a shared Redis-backed limiter.
- The audit chain detects database edits but does not prevent deletion by a database administrator. Anchor periodic root hashes in an external immutable store for stronger non-repudiation.
- HMAC proves possession of a shared key, not which individual supplier signed a file. Rotate compromised keys and migrate to asymmetric signatures for multi-party imports.
- Isolation Forest can produce false positives. Quarantine requires an analyst review path before real deployment.
- Forecast quality is measured only on synthetic data and is not evidence of real-world performance. Monitor drift and retrain only after validation.
- This release simulates purchase orders and does not connect to an ERP or payment system.

## Repository map

```text
backend/app/       API, security, analytics, persistence, seed data
backend/tests/     security, import, and end-to-end API tests
frontend/src/      React control tower
frontend/tests/    component and Playwright tests
.github/workflows/ CI and dependency checks
```

## Classroom documentation

Start with [docs/README.md](docs/README.md) for a plain-language project overview, a 6-8 minute live demo script, the technical reference, and a copy-paste prompt for generating the class presentation.
