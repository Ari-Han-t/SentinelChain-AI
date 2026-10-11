# Phase 3 — external integration inbox

Phase 3 adds administrator-managed connections for ERP, inventory, supplier and logistics systems. Synchronization stages validated source records in an encrypted review inbox. A separate, explicit reviewed import applies a source version to operational data through existing entity, inventory and Phase 2 policy checks. Mock adapters are synthetic development fixtures and cannot import operational data. No real partner connection has been configured or verified in this workspace.

## Local workflow

Run the existing backend and frontend, sign in as administrator and open **Integrations**. Add a connection (paused by default), enter a reason and confirm enabling it, then check and synchronize it. Inspect source identity/version, freshness, related entities and public data before confirming a live operational import. Reasons and outcomes are audited. Repeat synchronization safely: stable events and source versions are deduplicated. Check and sync are manually initiated; the UI refreshes health/history every 30 seconds. There is no background polling scheduler or outbound ERP write.

Development mock scenarios are healthy, recovered transient failure, rate-limited and invalid response. Their attempts and data are synthetic; actual HTTP retry behavior is exercised separately with HTTP mock transports. Production rejects new mock connections and refuses running existing mocks. A reachable health endpoint confirms reachability only; synchronization is tracked separately, and stale records cannot be imported.

## Backend profiles and credentials

Set `INTEGRATION_PROFILES_JSON` on the backend. For example:

```json
{"erp-primary":{"system":"erp","base_url":"https://partner.example/api","token_env":"SENTINEL_INTEGRATION_ERP_TOKEN","timeout_seconds":10,"max_attempts":3}}
```

Provision the named bearer-token environment variable through your deployment secret manager; never place credentials in a `VITE_` variable, connection form or source control. The browser receives profile names and system types only. Profiles require HTTPS without URL credentials/query/fragment. Requests reject private/loopback DNS addresses, redirects and proxy environment variables; certificate verification remains enabled. Enforce production egress allowlists as well: DNS prevalidation alone is not a full defense against DNS rebinding. Rotating a backend token requires refreshing the deployment environment/process. Credentials are never persisted in run history or audits. Supplier contacts in the inbox are encrypted and withheld from API responses.

The four adapters call `GET /health` (JSON `{"status":"ok"}`) and their system-specific endpoint: `/erp/changes`, `/inventory/changes`, `/supplier/changes` or `/logistics/changes`. Requests use bearer auth and an optional `cursor` query parameter. Profiles point at the base API path. These are normalized contracts; vendor-specific APIs require a translation layer/adapter implementation. They are not prebuilt SAP, Oracle or carrier integrations.

## Normalized source contract

```json
{"records":[{"event_id":"supplier-event-001","external_id":"supplier-001","resource":"suppliers","source_version":1,"occurred_at":"2026-10-11T00:00:00Z","data":{"name":"Example Components","reliability":0.97,"average_lead_time":6,"defect_rate":0.01,"price_variance":0.03,"compliance_status":"compliant","identity_status":"verified"}}],"next_cursor":null}
```

Schemas in `backend/app/integrations/schemas.py` reject unknown fields, wrong resource/system pairings, invalid ranges and timestamps without timezones. Pages contain at most 200 records and one MiB of JSON; cursors are bounded to 256 characters and a non-advancing cursor fails. Each successful request stages one page atomically. **Synchronize next page** advances a partner cursor; `null` ends the page sequence. Partner feeds must provide durable incremental cursors and stable identifiers/version numbers.

| Adapter | Resources | Reviewed mapping |
|---|---|---|
| ERP | suppliers, products, purchase-orders | PO `supplier_external_id` maps to an already imported supplier in that connection, or an explicitly selected local supplier. SKU references still use existing product validation. |
| Inventory | warehouses, inventory, stock-movements | Inventory `warehouse_external_id` maps to an imported warehouse or explicit local warehouse. Movement `lot_external_id` maps to an imported inventory lot or explicit parent. Parent local version is required. |
| Supplier | suppliers | Compliance/identity evidence remains in the inbox; non-compliant/disputed sources propose critical entity risk, subject to active policy. Existing governance is preserved otherwise. |
| Logistics | shipments, tracking-events | Shipment `purchase_order_external_id` maps to an imported PO or explicit local PO. Tracking requires a shipment parent version. Reported carrier status and ETA are evidence; they do not overwrite the governed shipment workflow status. |

New core entities use the existing governance defaults; existing entities require the current local version and preserve owner, stage, clearance and workflow state. Already imported external identities cannot be remapped. Stock movements/tracking events apply once; a correction requires a new external event identity. Inventory imports retain quantity, quarantine, warehouse, product and policy guards. Negative stock and stale review versions are rejected. Tracking adds an event without approving shipment delivery.

## Reliability and administration API

All `/integrations` routes require an administrator and a valid active policy. Connection mode/profile are immutable after creation; create another connection to change them. Enable/pause changes require the connection version and a reason. Pause blocks subsequent run/import requests; it is not cancellation of a request already executing.

- `GET /integrations/profiles`: safe profile inventory and mock availability.
- `GET /integrations` / `POST /integrations`: list/create connections.
- `POST /integrations/{id}/state`: versioned enable/pause.
- `POST /integrations/{id}/check` or `/sync`: reason plus a unique `idempotency_key` (8–80 letters, digits, `_`, `-`). Reusing a key returns the existing run; using it for another operation conflicts.
- `GET /integrations/{id}/runs`: paginated history; current UI shows latest 30 runs.
- `GET /integrations/{id}/records` and `/records/{record_id}`: encrypted inbox metadata/public data; review/search pagination.
- `POST /integrations/{id}/records/{record_id}/apply`: `expected_source_version`, optional target/parent identity, required local version for existing entities/event parents and reason.

Timeouts are bounded to 10 seconds, attempts to three. Transient network/408/500/502/503/504 failures use exponential retry delays; authentication/redirect/unsupported/schema failures do not retry. HTTP 429 honors bounded `Retry-After` (numeric or HTTP date); longer cooldowns are stored and prevent an early manual retry. Raw partner error bodies are never exposed. Run history separates running/succeeded/failed states, counts, safe error codes and timestamps. A database lease prevents simultaneous runs on one connection; an expired interrupted run is marked failed when a new run recovers the lease.

Event identifier reuse with different content fails the entire page. Same source versions with different payloads also fail; older versions are counted and ignored. Current-source duplicate confirmation refreshes freshness; old versions do not. Cursor, staged records and successful run accounting commit together. Operational imports and their applied-version/audit markers commit together. PostgreSQL row locks refresh source/target state before reviewed writes; unique constraints and local-version checks provide additional conflict guards. PostgreSQL multi-worker behavior has not been exercised here.

## Migration and verification

Apply `backend/alembic/versions/0007_integrations.py` with `alembic upgrade head` before deployment. It adds connections, runs, encrypted records and event deduplication tables after migration 0006. SQLite upgrade/downgrade/re-upgrade and local automated tests are verified during development; no real PostgreSQL service or vendor credentials are available. Unit HTTP transports do not prove an actual partner connection. Browser verification uses a separate synthetic preview database.

Phase 1/2 behavior remains in place. Integration tests cover admin-only access, all four mock adapters, live-transport simulation, retries/cooldowns, redaction, replay rollback, version ordering, policy denial, source freshness, parent mapping, one-time inventory movements and workflow-safe tracking imports. Component tests cover mock provenance, reason gating, failure alerts and load errors. Real-partner contract/credentials/egress tests and PostgreSQL deployment validation remain deployment work.

Local verification: the full backend suite passed 143 tests with the bundled scikit-learn OpenMP library directory set in `DYLD_LIBRARY_PATH`; the integration suite subsequently passed all 27 tests, including an additional incoming critical-risk regression. The frontend suite passed all 17 component tests. Frontend component suite and production build pass. SQLite fresh upgrade to 0007, downgrade to 0006 and re-upgrade pass. The Phase 3 Playwright scenario is present, but Chrome aborted at launch (SIGABRT/EPERM) before any browser assertions ran. The local in-app browser successfully exercised paused creation, explicit enabling, check, sync, duplicate sync and blocked mock import at desktop/mobile sizes.
