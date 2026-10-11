# Deployment and recovery

## Readiness status

The code includes PostgreSQL configuration/migrations and a guarded real-database verification script. **PostgreSQL has not been tested in this local environment. Do not call this deployment production-ready until the controlled PostgreSQL checks and operational checklist below pass.** SQLite regression tests cannot establish PostgreSQL correctness. CI configuration is supplied; its remote execution has not been observed.

## Configuration and local development

Use Python 3.12+, the pinned `backend/requirements.txt`, Node 22 and `npm ci` in `frontend`. Copy `.env.example` into `backend/.env` (untracked); select `AI_PROVIDER=deterministic` to run without AI credentials. Run `alembic upgrade head` from `backend`, then `uvicorn app.main:app --host 127.0.0.1 --port 8000`. Run `npm run dev -- --host 127.0.0.1 --port 5173` from `frontend`, with `VITE_API_URL=http://127.0.0.1:8000`. Demo accounts are synthetic and never enabled in production.

`.env.production.example` contains placeholders only. Replace each secret independently through a secret manager. Keep database, integration and AI credentials out of frontend `VITE_` variables. Startup rejects production SQLite, demo execution, demo seeding, duplicate/short development secrets and non-HTTPS/wildcard CORS origins. Production startup checks the migration revision; it does not call `create_all` or automatically alter tables. Configure database TLS with certificate validation (`sslmode=verify-full` and your trusted CA). Run behind an HTTPS reverse proxy with bounded bodies/timeouts and a shared rate limiter. JWT lifetime is 5–120 minutes (30 default); roles are reread from the database, not trusted from token claims. Tokens currently reside in session storage: prioritize an HttpOnly-cookie session architecture and revocation strategy before a public production launch.

## PostgreSQL validation

Provision a new, empty **disposable** PostgreSQL database named `sentinel_test_*`. Give its test user migration authority only for that database. Set `SENTINEL_TEST_POSTGRES_URL` through an untracked file or secret injection. From the project root run:

```sh
backend/.venv/bin/python scripts/verify_postgres.py
```

Without a URL it exits 2 with `NOT RUN`; other database names are refused. It applies migrations, seeds synthetic fixtures, exercises readiness/API/notifications, generates concurrent denied requests, verifies the hash chain, and confirms PostgreSQL rejects audit UPDATE. It retains fixtures for inspection; it never drops the database. Run in a controlled network with no live integration profiles. This command is separate from the SQLite suite. The supplied GitHub Actions job provisions PostgreSQL 16 and runs it, plus backend/frontend/browser tests.

## Least privilege and migrations

Use separate migration-owner and runtime database identities. The runtime identity must not own tables, create schemas, bypass row triggers, or be a superuser. Grant CONNECT, schema USAGE, SELECT/INSERT/UPDATE only on operational tables, sequence USAGE, and **SELECT/INSERT only on `audit_events`**. Revoke UPDATE/DELETE/TRUNCATE on that table. Revision 0010 adds a PostgreSQL BEFORE UPDATE/DELETE trigger as an extra barrier. A table owner/superuser can disable/drop it; a hash chain is tamper-evident, not an external proof of completeness. Export signed audit checkpoints to protected storage for stronger assurance. Restrict audit backup access to authorized operators.

The API Docker image starts Uvicorn only; it does not run migrations with runtime credentials. For development Compose, run `docker compose run --rm api alembic upgrade head` before `docker compose up --build`. The existing Compose file is development-only and its synthetic credentials must never be reused in deployment. Apply migrations once in a deployment job, using the owner identity, before starting runtime workers. Pin the reviewed release and database backup; run `alembic current` and `alembic upgrade head`, then check `/ready` and smoke-test authorized workflows. A migration failure must stop rollout. Do not grant runtime DDL merely to recover startup. Revision 0010 is reversible in a disposable database; downgrading removes simulation history and audit protection. Never automatically downgrade production after a failed deploy. Prefer redeploying the prior compatible application and a reviewed forward fix; restore only through a rehearsed recovery plan.

Connection pools are per process: `DATABASE_POOL_SIZE` (5), `DATABASE_MAX_OVERFLOW` (10), `DATABASE_POOL_TIMEOUT` (10 seconds), pre-ping and 30-minute recycle. Budget the maximum across workers against database capacity. Connections set UTC; Python comparisons normalize SQLite-naive/PostgreSQL-aware timestamps. Database exceptions return a safe 503 without SQL/credentials. `/health` is process liveness; `/ready` checks database connectivity and policy availability. Request logs contain generated correlation ID, method, status and duration, excluding headers, body, query string and identity data. Configure your logging collector/retention; the app does not provision one.

## Backup and recovery procedure

1. Define RPO/RTO, backup owner, retention and protected encryption keys. Run `pg_dump --format=custom` with the authorized backup identity and secret-injected connection. Do not put passwords in checked-in scripts or logs.
2. Encrypt/store dumps and the matching deployment/migration version in restricted storage. Back up field-encryption and import-signing secrets through your secret manager. A DB dump without encryption keys cannot recover encrypted contacts.
3. Restore with `pg_restore` into a new isolated database; never overwrite the production database as a drill. Apply compatible migrations, verify counts/foreign keys/audit integrity, then exercise login, entity access, recommendation decisions, integration idempotence and notification escalation.
4. Rehearse the drill and measure recovery time. Record approval, cutover and rollback criteria before a real incident.

No backup was created or restored during this implementation; this is a procedure, not a completed operational exercise.

## Release checklist

- [ ] Real PostgreSQL verification and API smoke tests pass on the target version.
- [ ] Runtime least privilege and audit UPDATE/DELETE/TRUNCATE denial are verified with runtime credentials.
- [ ] Backups and isolated restore drill meet RPO/RTO; secrets are recoverable.
- [ ] HTTPS/TLS, trusted proxy configuration, shared ingress rate limiting and body/time limits are verified.
- [ ] Bootstrap credentials are removed from runtime injection after initial setup.
- [ ] AI/integration destinations and credentials are configured and tested with approved systems; mock data remains labeled.
- [ ] Monitoring/error collection, on-call ownership, notification worker availability and alert escalation are verified.
- [ ] Dependency/advisory scanning and a scoped security review are run before launch.

Current process rate limiting is bounded to 10,000 client addresses, operates per worker and does not trust forwarded addresses. Shared/proxy-aware throttling belongs at ingress. Monitoring/notification loops are process tasks, not a distributed durable queue. Audit/history filtering still performs derived scope checks in Python and full-chain verification; benchmark and index/materialize metadata for large datasets. Self-host incumbent fonts before production; static frontend CSP currently permits their configured Google font origins. Email is unconfigured. External integrations remain dependent on configured credentials and real partner validation (see PHASE3.md).
