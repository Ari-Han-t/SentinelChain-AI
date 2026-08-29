# SentinelChain AI

SentinelChain AI is a security-first supply-chain control tower. It forecasts demand, calculates inventory policy, scores supplier risk, quarantines suspicious operational data, and keeps a tamper-evident record of every sensitive decision.

> All included data and displayed metrics are synthetic. The application is an academic demonstration, not a production-certified procurement system.

## What the demo proves

1. An analyst works from signed, schema-checked sales data.
2. The forecasting service compares an XGBoost model against a moving-average baseline.
3. Inventory policy explains safety stock, reorder point, EOQ, and the final order quantity.
4. An administrator injects demand poisoning, stock manipulation, or supplier spoofing.
5. SentinelChain blocks the input before it reaches forecasting and contrasts the unsafe order with the protected decision.
6. A procurement manager must approve any simulated purchase order.
7. An auditor can verify the complete hash chain.

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

The backend suite covers authentication, role boundaries, HMAC tamper detection, AES-GCM behavior, quarantine isolation, duplicate imports, forecasting, approval conflicts, attack containment, and audit-chain tampering. The frontend suite covers login success and recoverable authentication failure. A Playwright scenario exercises the full attack demonstration.

## Deployment

- `docker-compose.yml` runs the full local stack with PostgreSQL.
- `render.yaml` defines the API and managed PostgreSQL service. Set `CORS_ORIGINS` to the deployed frontend and keep `DEMO_MODE=false` for any production-labelled environment.
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

