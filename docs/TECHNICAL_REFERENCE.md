# Technical reference

## Architecture

```text
React 19 + TypeScript + Vite
        |
        | HTTP + JWT
        v
FastAPI + Pydantic + SQLAlchemy
        |              |
        |              +--> XGBoost / scikit-learn analytics
        |              +--> deterministic or Azure AI Foundry guidance
        |              +--> Argon2, AES-GCM, HMAC, SHA-256 controls
        v
PostgreSQL 16
```

Docker Compose runs three services:

| Service | Container technology | Host access |
|---|---|---|
| `web` | Nginx serving the built React app | `http://localhost:5173` |
| `api` | Python 3.13, FastAPI, Uvicorn | `http://localhost:8000` |
| `db` | PostgreSQL 16 Alpine | Internal Docker network only |

The API runs Alembic migrations before Uvicorn starts. PostgreSQL data persists in the `postgres_data` Docker volume.

## Main modules

| File | Responsibility |
|---|---|
| `frontend/src/App.tsx` | Login, role-aware workspace, topology, inspectors, actions, audit, and attack drill |
| `frontend/src/api.ts` | Typed HTTP client and frontend data contracts |
| `backend/app/main.py` | API routes, authorization boundaries, data flow, and monitoring loop |
| `backend/app/models.py` | SQLAlchemy tables and role definitions |
| `backend/app/analytics.py` | CSV validation, anomaly detection, forecasting, inventory policy, supplier risk |
| `backend/app/guidance.py` | Deterministic guidance and optional Azure AI Foundry integration |
| `backend/app/security.py` | Passwords, JWTs, HMAC, AES-GCM, and role dependencies |
| `backend/app/audit.py` | Append-only hash-chain creation and verification |
| `backend/app/seed.py` | Small default/test seed |
| `backend/app/demo_data.py` | Rich, idempotent classroom dataset loader |

## Core database entities

| Entity | Purpose |
|---|---|
| `User`, `UserContext` | Identity, role, owned stages, and escalation preferences |
| `OrganizationProfile` | Governed business context supplied to guidance |
| `SupplyChainNode`, `SupplyChainEdge` | Operational topology and current state |
| `EvidenceRecord` | Provenance, confidence, status, payload digest, and conflict key |
| `GuidanceRun`, `ActionProposal` | Evidence-backed advice and human decision state |
| `Product`, `SaleRecord`, `Supplier` | Inventory and analytical inputs |
| `ImportBatch`, `QuarantinedRecord` | Signed dataset lineage and rejected rows |
| `Forecast`, `Recommendation` | Model metrics and inventory policy output |
| `Alert` | Operational and security exceptions |
| `AuditEvent` | Hash-linked history of sensitive operations |

## API routes

Interactive request and response schemas are available at <http://localhost:8000/docs>.

| Method and path | Purpose | Access |
|---|---|---|
| `GET /health` | Liveness response | Public |
| `POST /auth/login` | Exchange demo credentials for a JWT | Public |
| `GET /auth/me` | Return current identity | Authenticated |
| `GET, PUT /organization/context` | Read or update governed business context | Read: authenticated; write: administrator |
| `GET, PUT /users/me/context` | Read or update the current user's operating context | Authenticated |
| `POST /supply-chain/blueprint/draft` | Return a proposed operating graph | Administrator |
| `POST /supply-chain/blueprint/activate` | Activate nodes and edges | Administrator |
| `GET /supply-chain` | Return organization, graph, status, and pending counts | Authenticated |
| `POST /events` | Add authenticated system evidence | Administrator or analyst |
| `POST /nodes/{id}/manual-events` | Add structured human evidence | Administrator, analyst, or manager |
| `GET /nodes/{id}/inspector` | Return a node, its latest evidence, guidance, and actions | Authenticated |
| `POST /nodes/{id}/guidance/refresh` | Mark old guidance stale and regenerate it | Authenticated |
| `GET /actions` | List role-relevant action proposals | Authenticated |
| `POST /actions/{id}/decision` | Approve or reject a pending action | Administrator or manager |
| `GET /dashboard` | Return KPIs, recent demand, products, alerts, and recommendations | Authenticated |
| `POST /imports/preview` | Validate a signed CSV without saving it | Administrator or analyst |
| `POST /imports` | Save accepted rows and quarantine rejected rows | Administrator or analyst |
| `POST /forecasts/{sku}/train` | Train and store a 14-day demand forecast | Administrator or analyst |
| `GET /forecasts/{sku}` | Return the latest stored forecast | Authenticated |
| `POST /recommendations/generate/{sku}` | Calculate and store an inventory recommendation | Administrator or analyst |
| `GET /recommendations` | List inventory recommendations | Authenticated |
| `POST /recommendations/{id}/decision` | Approve or reject a pending recommendation | Administrator or manager |
| `GET /suppliers` | Return suppliers and calculated risk scores | Authenticated |
| `GET /alerts` | Return alerts | Authenticated |
| `GET /audit` | Verify and return the latest 100 audit events | Administrator or auditor |
| `POST /demo/attacks` | Run a synthetic poisoning, manipulation, or spoofing drill | Administrator; demo mode only |

## Analytics

Forecast features:

- Previous day's demand (`lag_1`)
- Demand seven days earlier (`lag_7`)
- Previous seven-day rolling mean (`rolling_7`)
- Day of week
- Month

The model uses an 80/20 chronological split and reports MAE, RMSE, MAPE, and a seven-day moving-average baseline MAE. XGBoost feature contributions provide the explanation; scikit-learn Gradient Boosting is the fallback if XGBoost cannot be imported.

Inventory policy uses:

```text
safety stock = service factor * demand standard deviation * sqrt(lead time)
reorder point = daily demand * lead time + safety stock
EOQ = sqrt(2 * annual demand * order cost / annual holding cost)
```

Supplier risk combines reliability, lead time, defect rate, and price variance into a score from 0 to 100.

## Security controls and trust boundaries

| Boundary | Control | Failure behavior |
|---|---|---|
| User to API | JWT plus role checks | Returns 401 or 403 |
| CSV source to trusted sales | HMAC, schema checks, business rules, Isolation Forest | Rejects the file or quarantines individual rows |
| Supplier contact storage | AES-GCM authenticated encryption | Modified ciphertext cannot decrypt successfully |
| Evidence conflict | Stable conflict key and content digest | Keeps both records, marks them disputed, and changes node state |
| Guidance provider | Untrusted evidence framing, Pydantic schema, valid cited-ID check | Falls back to deterministic guidance |
| Human decision | Role check plus expected `pending` state | Repeated or stale decision returns HTTP 409 |
| Audit history | SHA-256 hash chain | Verification returns the first broken sequence |
| Demo attacks | Administrator check and `DEMO_MODE` gate | Route returns 403 or 404 |

## Demo accounts

All local demo accounts use `demo1234`.

| Role | Email |
|---|---|
| Administrator | `admin@sentinelchain.local` |
| Inventory analyst | `analyst@sentinelchain.local` |
| Procurement manager | `manager@sentinelchain.local` |
| Auditor | `auditor@sentinelchain.local` |

Never reuse these credentials outside the local synthetic environment.

## Operations

Start or rebuild:

```powershell
docker compose up --build -d
```

Inspect status and logs:

```powershell
docker compose ps
docker compose logs --tail 100 api web db
```

Load the classroom dataset:

```powershell
docker compose build api
docker compose run --rm api python -m app.demo_data
docker compose up -d api
```

Stop containers while retaining PostgreSQL data:

```powershell
docker compose down
```

Run tests from locally installed dependencies:

```powershell
cd backend
pytest -q
cd ..\frontend
npm test -- --run
npm run build
```

## Design trade-offs and limitations

- PostgreSQL is persistent and realistic for Docker, while SQLite keeps local tests fast.
- The process-local rate limiter is simple but does not coordinate multiple API instances.
- A database hash chain detects edits but cannot by itself prove that a privileged administrator did not delete the entire chain.
- HMAC uses a shared secret. Asymmetric signatures would identify individual external senders more strongly.
- Isolation Forest can flag legitimate demand changes, so suspicious input is quarantined instead of deleted.
- Synthetic forecast metrics demonstrate the workflow, not real business accuracy.
- The application proposes purchase actions but deliberately does not execute ERP or payment operations.

## Related

- [Project overview](PROJECT_OVERVIEW.md)
- [Classroom demo](CLASSROOM_DEMO.md)

