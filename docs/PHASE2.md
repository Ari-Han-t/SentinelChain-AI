# Phase 2 — Administrator policy configuration

Phase 2 extends the existing React/TypeScript and FastAPI/SQLAlchemy application. Phase 1 entity management, stage administration, forecasts, imports, operational routes, approvals, audit verification and synthetic attack simulations are retained.

## Administrator workflow

Sign in as an administrator and open **Policies** in the sidebar. The screen shows the currently published revision, effective role permissions, clearance floors, approval thresholds, operation rules, version history, and user role assignments.

1. Create a policy draft from the published configuration.
2. Edit permission assignments, entity/operation clearance requirements, recommendation approval thresholds, or typed operation rules.
3. Provide a draft reason and save. The draft is immutable and has no effect on authorization.
4. Review the published/proposed comparison and full proposed settings. Provide a separate publication reason and explicitly confirm publication.
5. To restore a previously published configuration, review restoration, provide a reason, and confirm. Restoration creates a new revision; historical revisions remain unchanged.

Saved drafts are not editable in place. Create a fresh draft when the published generation has changed. User role assignments have a separate review, expected-current-role check, reason and confirmation. Changes apply to existing tokens because the backend resolves the database role on every protected request. Administrators cannot change their own role; role assignments are serialized on the policy singleton and administrator authority is refreshed under that lock.

## Policy model and security boundaries

`PolicyRevision` stores a canonical typed configuration, SHA-256 integrity digest, draft/published status, base generation, creator, timestamps and reason. Publication records the publisher and timestamp. `PolicyState` is the singleton active revision pointer with a monotonically increasing generation.

Initial provisioning installs a baseline matching prior behavior. Runtime requests never silently fall back to built-in grants when policy state is missing or invalid. Missing pointers, corrupt configurations/digests, and non-published active revisions return 503 on authenticated operational routes. If database evaluation itself fails, operations also fail instead of being authorized. Initial provisioning refuses to reset a missing pointer when historical revisions already exist.

Only the immutable administrator role can draft, publish, restore or assign roles. Configurable permission assignments are subsets of existing role ceilings: they can remove and re-enable supported capabilities but cannot introduce capabilities outside a role's ceiling. Administrator capabilities and numeric role-clearance levels are fixed to preserve recovery authority. Existing route role ceilings continue to apply in addition to published permission grants.

Explicit capabilities were added for existing inventory, procurement and logistics writes, preserving their original role allowances. Previously listed permissions now control their corresponding protected API commands, including evidence submission, guidance refresh, forecasting/imports, recommendation generation, decisions, escalation, verification and audit reading. Unrelated legacy task, document, risk and workflow route role guards remain fixed; this phase does not create a general-purpose authorization language or configure arbitrary routes.

Entity clearance is the maximum of the published kind-wide floor and the entity's Phase 1 requirement. Parent clearance/deactivation protections remain enforced in both management and legacy routes. Policy configuration cannot lower an entity-specific requirement.

Supported sensitive operations:

| Operation | Backend enforcement |
| --- | --- |
| `inventory.change` | Legacy lot creation/movements, management lot creation/quantity changes, and product current-stock changes |
| `supplier.update` | Supplier management create/edit/deactivate/restore |
| `forecast.modify` | Forecast training and signed demand imports, evaluated before operational rows are written |
| `approval.decide` | Positive action/recommendation approvals; rejected decisions remain available to authorized users |

Rules have a unique key, operation, priority, activation flag, minimum clearance, optional governance-risk denial level, optional absolute inventory quantity limit, and optional timezone-qualified effective start/end. Effective windows use current UTC time; the end is exclusive. All matching active restrictions combine. No later rule can override a denial. Lower numeric priorities are evaluated first. Risk conditions use assigned entity governance risk (and action urgency for action approval), not unverified AI output. Legacy records without assigned governance risk use `low`; this is an explicit compatibility default, not a computed risk assessment.

Recommendation approval thresholds compare actual recommended quantity and numeric supplier-risk score. Managers are blocked at or above either threshold; administrators retain this approval authority, while explicit operation rules still apply to them. Baseline thresholds (quantity 1,000,000,000; risk 100) preserve prior normal demo behavior. Configure appropriate organization-specific thresholds before deployment.

Configurations reject unknown fields, unsupported operations, missing role/kind/operation assignments, unknown or escalated permissions, duplicate rule keys, invalid ranges, non-finite values, timezone-less/inverted date windows, and quantity conditions on non-inventory operations. Publishing revalidates configuration and integrity. A compare-and-swap update prevents publication/restoration against a stale generation. Draft publication also verifies its original base generation.

Policy changes and role assignments append actor, server timestamp, reason, previous/new configuration or role, and revision identifiers to the existing tamper-evident audit ledger. Allowed/denied sensitive operation evaluations and revoked-capability denials record their policy revision and generation. Denied operation evaluations are committed before returning 403; these checks occur before operational mutations so denials do not partially apply changes. The version-history table shows the original draft/restoration reason; the separate publication reason and full before/after snapshots are recorded in the audit API.

AI-generated content has no publishing or authorization path. Read-driven/background guidance remains an existing automatic monitoring function; restricting a user's refresh command does not turn off system monitoring.

## API contracts

All endpoints require bearer authentication and administrator authority.

| Method / path | Contract |
| --- | --- |
| `GET /security/policies` | Active configuration, generation, active revision, ceilings, role levels, immutable revision history and user directory (no credentials/email) |
| `POST /security/policies/drafts` | `{configuration, expected_generation, reason}`; validates and saves immutable draft; 201 |
| `POST /security/policies/{id}/publish` | `{expected_generation, reason}`; publish reviewed draft; 409 for stale/non-draft revisions |
| `POST /security/policies/{id}/revert` | `{expected_generation, reason}`; copy a published historical configuration into a new active revision |
| `POST /security/policies/users/{id}/role` | `{role, expected_role, reason}`; guarded role assignment; self-assignment or stale roles rejected |

`GET /auth/permissions`, clearance matrix, and stage specification report published effective grants. Existing API role guards and clearance remain server-enforced. Full schemas are available in the existing `/docs` OpenAPI page.

## Files and migration

Added `backend/app/policies.py`, migration `backend/alembic/versions/0006_policy_configuration.py`, `backend/tests/test_policies.py`, `frontend/src/PolicyAdministration.tsx`, its component tests, and `frontend/tests/e2e/policies.spec.ts`.

Updated models, startup/seed provisioning, authentication/route guards, stage capability descriptions, entity clearance/operation checks, operational routes, frontend API contracts/navigation/styles, Playwright port configuration, and README. Phase 1 changes remain in the working tree. No packages or credentials were added and no commit was created.

Apply migrations before starting the backend:

```sh
cd backend
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m uvicorn app.main:app --reload
```

Start the existing frontend in another terminal:

```sh
cd frontend
npm run dev
```

No new environment variables are required. Existing production secrets and configuration requirements still apply. The demo account `admin@sentinelchain.local` / `demo1234` is for seeded development only. The live verification preview uses `backend/phase2-preview.db`, deterministic guidance and localhost ports 5175/8101, separate from the normal application database.

Tests on this Mac use the existing installed scientific-wheel OpenMP runtime:

```sh
cd backend
DYLD_LIBRARY_PATH="$PWD/.venv/lib/python3.12/site-packages/sklearn/.dylibs" .venv/bin/python -m pytest -q
```

```sh
cd frontend
npm test -- --run
npm run build
E2E_CHROME=1 E2E_WEB_PORT=5177 E2E_API_PORT=8103 ./node_modules/.bin/playwright test tests/e2e/policies.spec.ts
```

Playwright defaults remain 5175/8101. Optional `E2E_WEB_PORT` and `E2E_API_PORT` isolate an automated run from an already running preview. `E2E_PYTHON` selects a nonstandard interpreter. The test uses an isolated synthetic database and never reuses arbitrary running servers.

## Verification and limitations

The Phase 1 regression suite passed while extending the backend: 86 backend and 8 frontend tests. Initial checks before renewed filesystem access were blocked by workspace permissions and were rerun after access was granted.

The new policy cases cover unauthorized administration/escalation, inactive drafts, immediate permission changes for existing tokens, direct API denials, validation, stale draft/publication/restoration conflicts, atomic inventory denial, supplier denial, entity clearance, approval thresholds/rejection, role assignments/self-protection, effective dates, missing/invalid policy state, and audit integrity. Final verification: **117 backend tests passed** (31 new policy cases), **12 frontend tests passed** (4 new policy component cases), **TypeScript/Vite production build passed**, and `git diff --check` passed. The visual reviewer scored the scoped typography and supplied product-context fixes resolved; this verdict is limited to those fixes.

The in-app browser exercised actual draft → comparison → publish → historical restoration against the isolated preview database, with restored baseline permissions and all three revisions retained. Desktop and mobile overview/form layouts were inspected. Playwright Chrome aborted with SIGABRT before test actions and reported sandbox process restrictions; automated end-to-end verification is **not passed**.

Migration 0006 fresh upgrade, downgrade to 0005, and re-upgrade passed on disposable SQLite. No real PostgreSQL instance was tested. PostgreSQL locking, compare-and-swap concurrency and deployment readiness require controlled PostgreSQL integration testing before production claims.

This phase intentionally does not support custom roles, per-user permission overrides, arbitrary executable conditions, separate reviewer/publisher identities, whole-policy scheduled publishing, global policy disablement, or online recovery from a corrupt active policy pointer. Operation-rule effective dates work at request evaluation time without a scheduler. Recover corrupt policy state through a controlled database backup/repair procedure; ordinary operations remain blocked. Schema downgrade removes policy history/state, so take a backup and do not use downgrade as a configuration rollback. Use reviewed restoration for normal policy rollback.

The history API is currently unpaginated and has no draft archive/delete endpoint. Existing multi-process audit sequencing and process-local rate-limiting limitations still apply. Existing dependency advisories from Phase 1 remain documented; this phase did not update package versions. The UI refreshes cached grants periodically and after local policy changes, while backend authorization uses the published policy on every request.
