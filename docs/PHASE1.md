# Phase 1 entity management

Phase 1 extends the existing SentinelChain application with functional entity management in **Operations → Entities**. The existing React control tower, FastAPI authentication, deterministic stage permissions, analytics, attack simulations, and audit chain remain in place. Entity mutations are administrator-only; other authenticated roles can read records allowed by their server-owned clearance level.

## Existing implementation and changes

The application uses React 19, TypeScript, Vite, TanStack Query, FastAPI, Pydantic, SQLAlchemy and Alembic. Authentication uses Argon2 and JWTs; route guards load the current database user. Stage and chain creation, editing, deactivation, restoration, evidence, recommendations and approvals already existed. The operational modules previously exposed mostly read-only lists; supplier management and warehouses were missing.

The new entity screen supports suppliers, warehouses, inventory items (existing products), inventory lots, draft purchase orders with typed lines, and shipments. Administrators can create, edit, deactivate and restore records. Search, active/inactive filters, sorting, details, loading/error/empty states, change reasons and success messages are functional. Stage management continues through the existing Control tower and Supply chains screens.

Entity details show operational fields, assigned owner, risk, required clearance, linked stage and applicable warehouse. Relationships include supplier orders, order shipments, warehouse inventory, lot movements and inspections, shipment tracking, and product forecasts/recommendations. Explicit stage links provide actual stage evidence, guidance and approvals; an empty relation stays empty. Supplier contact updates use existing AES-GCM encryption and are excluded from responses and audit payloads.

## Security and operational rules

- Only administrators have `entity.manage`; backend mutation routes independently require the administrator role.
- Clearance levels reuse the existing server map: auditor 1, analyst 2, manager 3, administrator 4. A linked parent’s stricter clearance also restricts inventory, orders and shipments.
- Legacy supplier, inventory, purchase-order, shipment, dashboard, forecast, recommendation, import, movement and inspection routes apply entity governance checks. Direct API calls cannot bypass the new clearance and deactivation rules.
- Management input rejects unknown fields, invalid numbers, non-finite values, blank identifiers, invalid owners/stages/warehouses and unknown inventory/order SKUs.
- Draft-order edits do not grant approvals or change order status. Non-draft orders remain read-only in the management editor. Existing approval workflows are preserved.
- Existing product/lot SKUs cannot be renamed. Quarantined lot quantities cannot be adjusted through the management form. Quantity changes create stock-movement history.
- Deactivation preserves records and history and prevents new operational changes, including changes involving a retired parent. Readable history remains available to authorized roles.
- Updates and state changes require the displayed `expected_version`; stale edits return 409. PostgreSQL row locks serialize management updates; legacy lot mutations increment governance versions.
- Audit events record actor, time, entity kind/ID, before/after values, and reason in the existing hash chain. Audit history is administrator/auditor-only. No contacts or ciphertext are included.

## API contract

`kind` is one of `suppliers`, `warehouses`, `products`, `inventory`, `purchase-orders`, or `shipments`. All routes require a bearer token.

| Method | Endpoint | Behavior |
|---|---|---|
| GET | `/entities/users` | Administrator-only owner directory, excluding email and credentials |
| GET | `/entities/{kind}` | Clearance-filtered list; `q`, `status=all\|active\|inactive`, `sort=name\|id\|risk` |
| GET | `/entities/{kind}/{id}` | Fields, governance, relationship records and authorized audit history |
| POST | `/entities/{kind}` | Administrator creates a validated record; returns 201 |
| PUT | `/entities/{kind}/{id}` | Administrator edits an active record using expected version |
| POST | `/entities/{kind}/{id}/state` | Administrator deactivates/restores with expected version and reason |

Create/update bodies:

```json
{
  "data": {"code": "WH-01", "name": "Main warehouse", "location": "Synthetic example"},
  "governance": {
    "owner_id": null,
    "stage_id": null,
    "warehouse_id": null,
    "risk_level": "low",
    "minimum_clearance": 1
  },
  "expected_version": 1,
  "reason": "Approved operational change"
}
```

Omit `expected_version` on creation. Warehouse assignment is supported only for inventory lots. `risk_level` accepts low/medium/high/critical; clearance accepts 1–4. IDs must reference existing records; linked stages must be active. Bodies and field constraints appear in the FastAPI OpenAPI documentation.

State body: `{"active": false, "expected_version": 1, "reason": "Retired location"}`. Errors use 401 (no valid authentication), 403 (role/clearance), 404 (unknown record/type), 409 (duplicate, stale edit, inactive record or operational conflict), and 422 (validation).

## Files and database migration

- `backend/app/entities.py`: entity API, typed input, references, governance, relationships and audit history.
- `backend/app/models.py`: `Warehouse` and `EntityGovernance` tables; existing operational models retained.
- `backend/app/main.py`: router registration and governance on existing operational routes.
- `backend/app/security.py`: administrator entity capability.
- `backend/alembic/versions/0005_entity_management.py`: additive warehouse/governance migration, indexed identifiers and foreign keys to users/stages/warehouses.
- `frontend/src/EntityManagement.tsx`: tables, inline forms, confirmations and details.
- `frontend/src/App.tsx`, `api.ts`, `styles.css`: Operations integration, API client, validation errors and responsive styling.
- `backend/tests/test_entities.py`, `frontend/tests/EntityManagement.test.tsx`: entity and security coverage.
- `frontend/tests/setup.ts`: isolated storage fixtures for Node versions exposing unbacked browser-storage globals.
- `frontend/playwright.config.ts`, `tests/e2e/entities.spec.ts`: portable isolated test server and browser workflow.

Upgrade an existing database with `cd backend && .venv/bin/python -m alembic upgrade head`. Back up an operational database first. The downgrade removes governance/warehouse tables and their data; use it only against a disposable database during testing. Startup also creates missing tables through the repository’s existing schema initialization.

## Local development

Use Python 3.12 or 3.13; the pinned scientific dependencies should not be installed into Python 3.14. From the repository root:

```sh
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m uvicorn app.main:app --reload
```

In a second terminal:

```sh
cd frontend
npm ci
npm run dev
```

Use existing environment examples for configuration. Keep secrets out of version control. The normal UI is at http://localhost:5173 and API documentation at http://localhost:8000/docs. Administrator demo login remains `admin@sentinelchain.local` / `demo1234` in seeded development only.

On this Mac, the initial forecast test failed because XGBoost could not locate OpenMP. The installed scikit-learn wheel includes a compatible runtime; this test command passed using it:

```sh
cd backend
DYLD_LIBRARY_PATH="$PWD/.venv/lib/python3.12/site-packages/sklearn/.dylibs" .venv/bin/python -m pytest -q
```

For normal Mac forecasting, install the official Homebrew `libomp` package or configure the same library path before starting the backend. No global runtime installation was made in this task.

## Verification and remaining limits

Baseline: 67 backend tests passed and the forecast test failed for missing OpenMP. The 3 original frontend tests failed on Node’s unbacked storage globals. Those environment issues were addressed for verification. Final results: **86 backend tests passed**, **8 frontend tests passed**, and the TypeScript/Vite production build passed. The backend suite includes 18 new entity cases. Existing dashboard, import, forecasting, stage administration, authorization, approval and attack-simulation regression tests pass.

The live browser workflow verified warehouse create, edit, deactivate, restore and audit history using `backend/e2e-sentinelchain.db`, separate from the normal database. Desktop and mobile views were inspected. The committed Playwright scenario remains unverified automatically: installed Chrome aborted on launch inside this execution sandbox. The test configuration uses dedicated ports 5175/8101, deterministic guidance, and an isolated synthetic database; it never reuses an arbitrary running server. On a normal development machine, install Playwright Chromium and run `npm run test:e2e`; set `E2E_CHROME=1` to use installed Chrome, or `E2E_PYTHON` for a nonstandard Python executable.

Revision 0005 upgrade, downgrade to 0004, and re-upgrade were checked on disposable SQLite. A real PostgreSQL instance has not been tested in this task; do not treat these results as PostgreSQL or production-readiness evidence.

Existing global alerts/incidents lack an entity foreign key and are not attributed to a record. Phase 1 therefore shows linked stage evidence and operational history, but a comprehensive entity incident history needs a later explicit incident relationship. List queries currently fetch records without pagination; optimize queries and introduce pagination before large deployments. Legacy routes retain their prior role allowances and compatibility with synthetic unregistered SKUs, while the new management API requires registered SKUs. Shipment/order state-transition expansion, administrator policy configuration, integrations and notifications belong to subsequent phases.

`npm ci` reported 11 existing dependency advisories (3 moderate, 6 high, 2 critical). Package versions were not changed by Phase 1; remediation requires a separate compatibility review. Existing process-local rate limiting and database-administrator audit-chain limitations remain as documented in README.
