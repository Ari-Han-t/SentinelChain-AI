# Phases 6–10 — security operations and deployment preparation

## Existing architecture and baseline (phase 10)

The existing system is React 19/TypeScript/Vite with TanStack Query, FastAPI, SQLAlchemy 2/Alembic, Argon2 password hashing and HS256 JWT authentication. Server role ceilings, published policy, entity clearance, CAS decision/configuration versions and a serialized hash-linked audit ledger are retained. Prior phases provide operational entity management, policies, modular external adapters, recommendation history and incidents. Repository source/configuration/migrations/tests and the original requirement file were inspected. Baseline: **172 backend / 25 frontend tests passed**. Incremental regression runs follow below; no core rewrite or deployment occurred.

## Attack simulations (phase 6)

`GET /security/simulations` (administrator/auditor with `audit.read`) returns paginated recorded results and available scenarios. `POST /security/simulations` accepts `{scenario, reason}` and requires an administrator with `demo.attack`. Execution is unavailable when DEMO_MODE=false or environment=production, regardless of a mistaken demo flag.

Eight scenarios cover a tampered signed demand import, invalid stock movement, an unauthorized supplier write, a forged administrator role claim, entity clearance bypass, unauthorized policy draft, disposable audit-evidence tampering, and duplicated/replayed mock ERP synchronization. A private FastAPI router reuses actual route handlers/dependencies against a **separate in-memory SQLite database** with synthetic fixtures and a copied published policy. No shared dependency override, remote adapter or operational database mutation is used. The main database receives only the authorized simulation record and completion audit event. Reports retain initial/final fixture state, actions/HTTP results, expected/observed outcome, detection/blocking, policy digest/revision, sandbox audit evidence, actor/time and final pass/fail. Tampering is detected after modification in the disposable ledger; it is not falsely labeled blocked. Legacy `/demo/attacks` remains available with its existing behavior and stronger production guard.

These are controlled checks of the named control paths, not an exhaustive penetration test or production database test. A more restrictive policy may produce an unexpected result; the report keeps it as failed rather than fabricating success.

## Audit visibility (phase 7)

`GET /security/audit`: action substring, actor_id, entity text, severity, outcome, timezone-aware `since`/`until`, offset and limit (30 default, 100 maximum). Response includes scoped records, identities, affected entity, timestamps, outcome/reason, captured policy revision/generation, server-generated request ID, related incident/action/recommendation/simulation/run, hashes and full-chain validity. Source clearance and administrator-only integration scope apply to both this endpoint and legacy `/audit`. No audit edit/delete endpoint exists. Legacy request/policy fields remain explicitly unavailable. An authorization decision not separately recorded is labeled accordingly, never inferred as a proven approval.

Audit payload construction redacts credential/token/password/contact/email/import-body fields recursively before hashing new events. A safe request context supplies correlation IDs without retaining headers or request bodies. Legacy stored events are redacted on presentation without rehashing/replacing their original data. Revision **0010** adds simulation persistence, composite audit indexes and a PostgreSQL append-only UPDATE/DELETE trigger. Audit hashes prove internal linkage; a malicious database owner can still tamper with or truncate storage, so runtime privileges and external checkpoints remain necessary.

## Interface (phase 8)

The new **Security** navigation consolidates unresolved incidents, audit integrity, real configured integration health and recent simulations. **Evidence** opens the richer audit explorer for authorized users. Audit filters/details and simulation review/confirmation/results reuse the existing flat workflow UI, readable states, local table scrolling and mono machine IDs and role-specific controls. Existing entity, supplier/inventory, policy, approval, recommendation, notification and integration screens remain functional. Loading/error recovery, empty results and explicitly disabled execution are supplied; no live integration or operational remediation is invented.

## Deployment preparation (phase 9)

PostgreSQL-only production configuration, pool settings, UTC normalization, migration-required production startup, readiness checks, response security headers, bounded request throttling and safe structured request logs were added. Example production environment, real PostgreSQL acceptance command, CI jobs, least-privilege/migration/backup/recovery procedures and release checklist are provided in DEPLOYMENT.md. **Production readiness remains unverified until a real PostgreSQL run and deployment/restore checks pass.** No local PostgreSQL instance or credentials are available as of implementation.

## Validation

Final counts/results and UI proof are recorded in the completion report. New backend regressions cover all scenarios and isolation (exactly one completion audit in the operational DB), permissions/production guard, safe audit filtering/redaction, request headers, readiness failure, entity clearance and timestamp normalization. Frontend tests cover reviewed execution, auditor read-only results, audit filters/legacy metadata and error recovery. CI includes unit, actual PostgreSQL and Playwright workflow checks; configuration is not evidence that CI has run.
