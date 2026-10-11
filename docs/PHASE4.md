# Phase 4 — recommendation explanations and history

The existing stock-planning recommendations and stage action proposals now share an authenticated **Recommendations** history screen. It lists/searches/filters/paginates generated issues, affected entities, risk category/severity, decision and implementation state. Details show source IDs, captured evidence, reasoning, potential consequences, mitigation, uncertainty, decisions and reports. Stock explanations use recorded forecast output and generation-time stock/cost inputs; stage explanations cite only evidence belonging to the source stage. Interpretation is labeled as such. No supplier-to-product contractual relationship is assumed.

New records capture an immutable application snapshot at generation. Guidance refreshes also capture separate stage risk assessments, including refreshes that reuse an unresolved action. This supports comparing recorded assessments without claiming that a recommendation caused a risk change. Previous stock snapshots for the same product are available in the detail view; the UI shows the latest ten related assessments.

Legacy records have no original input snapshot. They are labeled `legacy_not_captured`; stored outputs and currently available related records cannot reconstruct their original inputs. Legacy decisions not already captured retain the source's decision maker/note but do not gain fabricated historical events.

Provider and deterministic heuristic confidence values are **not calibrated probabilities**. History displays the absence of calibrated action confidence and missing source/outcome information; the existing guidance UI now labels confidence as uncalibrated instead of displaying an unsupported action-confidence percentage. Forecast error measures remain validation observations. No new AI provider or remote service is called by history endpoints.

## Human decision and implementation workflow

Existing approval routes remain functional. Their significant decision/audit events also appear in shared history. The new history workflow allows `pending → approved/rejected/dismissed/deferred` and `deferred → approved/rejected/dismissed`. A deferred source remains unresolved and cannot silently become an approved action. Guidance reuse includes deferred actions. Terminal decisions cannot be replaced through the history API.

Administrator/procurement-manager writes require the existing published `action.decide` permission. Product entity clearance, operational activity and published approval/risk/quantity rules are enforced server-side. Analysts and auditors read within their source scope and cannot write decisions or implementation reports. Stage history preserves the existing analyst team boundary. History does not broaden authority or execute purchase orders, stock changes or shipments.

Implementation feedback is explicitly **user reported**. State is `not_started`, `in_progress`, `completed`, `failed` or `cancelled`. Only approved recommendations may have a non-default implementation state. Final states require an outcome; completed/cancelled work cannot be reopened through the report API. Reports require the current progress version and a reason; a stale report conflicts. Decision/report events retain actor, timestamp, reason, policy revision/generation and audit linkage. Reports do not prove external execution or verified remediation.

## API

- `GET /recommendation-history`: `kind=all|stock|stage`, `status`, `severity`, `q`, `offset`, `limit` (default 30, maximum 100). Only authorized source rows are counted/returned.
- `GET /recommendation-history/{kind}/{source_id}`: explanation, current source decision/progress, event history and related risk snapshots.
- `POST /recommendation-history/{kind}/{source_id}/decision`: `decision`, `expected_status` (`pending|deferred`), `note` (3–1000 characters). Approval maps to the existing `approved` state; accepting a suggestion does not execute it.
- `POST /recommendation-history/{kind}/{source_id}/feedback`: `expected_version`, `implementation_status`, `outcome`, `feedback`, `reason`. Final implementation outcomes must contain at least three characters.

Migration **0008** adds recommendation snapshots, progress, history events, stage assessments and a transaction-scoped audit-writer lock. Audit writes are serialized on SQLite/PostgreSQL to preserve chain sequencing during concurrent denied requests. Notification reconciliation and related mutations take the same lock before their own incident/progress locks. PostgreSQL behavior still requires validation against a real server; SQLite concurrency tests are not a substitute.

## Verification and limits

Backend tests cover capture immutability, honest legacy views, assessment history, deferred/final decisions, old/new-route history, direct unauthorized requests, current clearance, published permissions/approval thresholds, version conflicts and implementation outcomes. Frontend tests cover confidence/legacy copy, confirmation-before-write, read-only controls and recovery states. Browser verification uses an isolated synthetic preview database and deterministic guidance. No actual partner operation, production remediation or calibrated AI confidence is claimed. Current list queries filter authorized records in application memory; production-scale query optimization belongs to deployment work.

Final phase 4/5 verification: 172 backend tests and 25 frontend tests pass; the frontend production build and `git diff --check` pass. SQLite upgrade to 0009, downgrade to 0007 and re-upgrade pass. In-app browser checks verified captured evidence, deferral followed by approval, user-reported implementation, personal read state, acknowledgement, resolution and an audited rule update. Desktop and 390px mobile captures were reviewed. The new Playwright scenario could not execute assertions because installed Chrome aborted at launch (`SIGABRT`/`EPERM`); this is not an end-to-end test pass. PostgreSQL and outbound email remain unverified/unconfigured.
