# Phase 5 — notifications, incidents and escalation

**Notifications** now provides personal in-app read/unread delivery, a scoped incident center and administrator routing rules. Notifications are driven by persistent application events and source/deadline checks. Email is explicitly unconfigured. Delivery adapters are defined in `backend/app/notifications/delivery.py`; adding another channel requires a configured provider, recipient policy and verified delivery/idempotency behavior. This release never sends email.

## Event sources

| Category | Persistent source and interpretation |
|---|---|
| Supplier risk | Stored supplier indicators with heuristic risk ≥80; synchronized identity/compliance records flagged non-compliant. Source claims remain unverified evidence. |
| Inventory change | Quarantined lots, guarded movements affecting quarantine, or movements at/above the configured quantity review threshold (default 10,000). A signal is not proof of manipulation. |
| Demand poisoning | Import quarantine/anomaly counts, relevant stored alerts and explicitly labeled demo attack events. Anomaly detection is not proof of malicious intent. |
| Supplier spoofing | Disputed supplier identities in the integration inbox and explicitly labeled demo spoofing events. |
| Unauthorized access | Rejected logins/tokens, role checks and entity-clearance checks. Credentials, login identifiers, raw request bodies and tokens are withheld. |
| Policy violation | Published permission denials and denied deterministic policy evaluations. Notification settings never weaken enforcement. |
| Pending approval | Stock/stage recommendations with pending or deferred decisions. Final source decisions automatically close these incidents; they cannot be manually resolved to bypass the decision workflow. |
| Integration failure | Actual persisted failed runs; mock failures remain labeled synthetic. Reachability/sync success is not fabricated. |
| Overdue remediation | Stored task/action deadlines passed without a final decision or a reported final approved-action implementation outcome. |

Demo attack audit records and their corresponding alert share a source key; they cannot create two incidents for one simulated event. Source references are unique across polling/retries. Rules suppress a disabled or below-threshold source. Existing source occurrences are not emitted again merely because a worker polls or an API request is retried.

## Workflow and rules

Personal delivery is tied to user ID; a user cannot mark another user's notification read. Current role, entity clearance and incident-source scope are reevaluated on read. Assignment never grants access. Security and integration incidents require administrator ownership; auditors may inspect authorized incidents but cannot acknowledge, resolve or own remediation. Teams are the existing operational roles, not a new organizational-directory feature. Assignment to a named user validates role membership and source access.

Incidents are `open`, `acknowledged` or `resolved`. Acknowledgement records actor/time but leaves the issue unresolved. Resolution requires a reason and records actor/time/note; it does not change source operational data. A stale incident version conflicts. A new source event after resolution starts a new linked incident episode, preserving the old resolution and its delivery history. Duplicate old source events do not reopen it.

Rules configure enabled state, minimum severity, responsible team/user, escalation team, critical-unresolved threshold, remediation deadline and inventory quantity threshold. Edits require administrator authority, the rule version, a reason and frontend review/confirmation. Changes apply to new incidents; recorded owners/deadlines on existing incidents remain intact. Published security policy remains separate.

A critical unresolved incident escalates once when its configured escalation time passes, including if acknowledged. Any unresolved incident also escalates once when remediation becomes overdue. Escalation notifies authorized members of the configured escalation team and records its reason/time in incident history and audit. Responsible/escalation recipients are filtered through current source access. An incident with no eligible recipient remains visible to an authorized administrator for reassignment.

## Processing and delivery

The API process checks sources and deadlines periodically (`NOTIFICATION_INTERVAL_SECONDS`, default 30, range 10–3600), using a worker thread and database writer lock. Administrators can run **Check sources and deadlines** immediately. Work stops with the API process; deadlines are checked again after restart. This is not a separate durable job runner or a claim of distributed delivery readiness.

In-app deliveries persist before display and have a unique incident/recipient/escalation-level/channel key. The adapter receives a stable idempotency key and only authorized metadata. Retryable adapter failures retry at most three attempts with 30/60-second backoff; permanent/unconfigured failures stop. Safe error codes, attempts, status and read timestamps appear in authorized incident delivery history. Pending deliveries for a resolved incident are cancelled. No raw provider errors or credentials are exposed.

An audit-writer lock serializes event projection and notification reconciliation. SQLite concurrent denied-request tests verify audit integrity and notification deduplication. Production PostgreSQL multi-worker locking, performance and a distributed email worker have not been verified.

## API

- `GET /notifications`: personal delivered notifications; `unread`, `offset`, `limit` (30 default, 100 maximum).
- `POST /notifications/{id}/read`: `{ "read": true|false }` for the current recipient only.
- `GET /incidents`: authorized incidents; `status`, `severity`, `category`, `q`, `offset`, `limit`.
- `GET /incidents/{id}`: lifecycle/history and authorized delivery history (administrators see all recipients; other users see their own deliveries).
- `POST /incidents/{id}/transition`: `expected_version`, `action` (`acknowledge|resolve|assign`), `reason`, assignment fields if relevant. Assignments require administrator authority.
- `GET /notification-rules` and `PUT /notification-rules/{category}`: administrator-only typed configuration, current version and reason.
- `POST /notifications/reconcile`: administrator-only source/deadline check; not a bypass of approval or authorization.

Migration **0009** adds rules, incidents, source occurrences, lifecycle history and deliveries after 0008. Apply `alembic upgrade head` before deployment. Backend tests cover personal read status, source deduplication, simulated audit/alert deduplication, version conflicts, role/clearance/assignment boundaries, rule thresholds, acknowledgement/resolution, recurrence, approval closure, overdue escalation, safe failure sources, bounded adapter retries and concurrent audit writes. Frontend tests cover read requests, reviewed transitions/configuration and auditor read-only controls.

Final phase 4/5 verification: 172 backend tests and 25 frontend tests pass; the frontend production build and `git diff --check` pass. SQLite upgrade to 0009, downgrade to 0007 and re-upgrade pass. In-app browser checks verified captured evidence, deferral followed by approval, user-reported implementation, personal read state, acknowledgement, resolution and an audited rule update. Desktop and 390px mobile captures were reviewed. The new Playwright scenario could not execute assertions because installed Chrome aborted at launch (`SIGABRT`/`EPERM`); this is not an end-to-end test pass. PostgreSQL and outbound email remain unverified/unconfigured.
