# Prompt to generate the class presentation

Copy the prompt below into ChatGPT, Gamma, Canva, Copilot, or another presentation generator. Ask it to export to PowerPoint after reviewing the draft.

```text
Create a polished 10-slide classroom presentation about my information-security project, "SentinelChain AI".

Audience: a university teacher and classmates with basic software and cybersecurity knowledge.
Duration: 7 minutes plus questions.
Tone: clear, technical, credible, and concise. Avoid marketing language and unsupported claims.
Visual style: dark industrial control-room theme, charcoal background, white text, restrained red for risk, thin graph lines, simple diagrams, and minimal text. Use 16:9 layout. Include speaker notes for every slide.

Project facts:
- SentinelChain AI is a security-first, graph-based supply-chain control tower for a synthetic industrial automation manufacturer.
- It connects six stages: demand planning, tier-1 suppliers, procurement and approvals, control-panel assembly, inbound/outbound logistics, and customer fulfilment.
- The stack is React 19 + TypeScript + Vite, FastAPI + Python, SQLAlchemy + PostgreSQL, and Docker Compose.
- Analytics use XGBoost with lag_1, lag_7, rolling_7, day-of-week, and month features. Results include MAE, RMSE, MAPE, and a moving-average baseline.
- Inventory outputs include safety stock, reorder point, EOQ, recommended quantity, and supplier risk.
- Optional Azure AI Foundry guidance is advisory. Responses are schema-validated, cited evidence IDs must exist, and deterministic guidance is the fallback.
- Security controls include Argon2 password hashing, short-lived JWT authentication, role-based authorization, AES-GCM encryption, HMAC-signed imports, schema/business-rule validation, Isolation Forest anomaly detection, quarantine, conflict-preserving evidence, expected-state approvals, rate limiting, and a SHA-256 audit hash chain.
- Four roles exist: administrator, inventory analyst, procurement manager, and auditor.
- Material actions require human approval. The system never places a real purchase order.
- All data is synthetic. The rich demo has 12 SKUs, 365 daily sales observations per SKU, 8 suppliers, 12 forecasts, 12 recommendations, 48 scenario evidence records, 12 scenario alerts, 5 quarantined rows, and 10 scenario action proposals.

Use this incident story throughout:
1. Hospital orders increase Safety Relay demand by 42% week over week.
2. Stock is 38 units and supplier lead time rises from 12 to 17 days.
3. The supplier reports 480 dispatched units, while the warehouse expects 320 for the same ASN.
4. A different supplier presents an untrusted TLS certificate and is blocked.
5. Chennai port congestion adds four days to a shipment.
6. The system marks evidence disputed, proposes reconciliation, production re-sequencing, alternate sourcing, and air freight.
7. A procurement manager must approve material actions.
8. Every event and decision enters a tamper-evident audit chain.

Build these slides:
1. Title: SentinelChain AI, with subtitle "Secure supply-chain decisions from evidence to approval" and placeholders for student name, course, teacher, and date.
2. Problem: show how bad, late, conflicting, or malicious data can cause stockouts and unsafe purchasing decisions.
3. Solution: explain Observe -> Verify -> Explain -> Approve -> Audit in one flow diagram.
4. Architecture: browser -> FastAPI -> validation/analytics/guidance -> PostgreSQL, with security controls at trust boundaries.
5. Synthetic dataset: use clean metric cards for products, sales, suppliers, evidence, alerts, and quarantined records. Clearly label all values synthetic.
6. Live incident: use a timeline of the Safety Relay demand surge, lead-time delay, conflicting ASN, certificate block, and logistics disruption.
7. AI and analytics: distinguish XGBoost demand forecasting from advisory Azure AI Foundry guidance; explain deterministic fallback and evidence citations.
8. Information-security controls: map threat to control, including poisoning -> quarantine, spoofing -> certificate/HMAC validation, privilege abuse -> RBAC, tampering -> hash chain, unsafe automation -> human approval.
9. Live demo plan: login, inspect the disputed supplier node, review evidence, approve/reject an action, verify the audit chain, run one attack drill.
10. Results, limitations, and next steps: state what the prototype demonstrates, honestly list limits, and propose ERP integration, asymmetric supplier signatures, Redis rate limiting, external audit anchoring, and model-drift monitoring.

For each slide provide:
- A short title.
- No more than 4 concise bullets or labels.
- A suggested visual or diagram.
- Speaker notes of 60-100 words in natural language.
- One transition sentence to the next slide.

Rules:
- Do not claim the data, customers, suppliers, attacks, or forecast accuracy are real.
- Do not call the audit chain a blockchain.
- Do not imply AI autonomously executes purchases.
- Define HMAC, AES-GCM, RBAC, MAE, and EOQ briefly on first use.
- Favor diagrams, metric cards, and a threat-control table over paragraphs.
- End with a final one-sentence takeaway: "Trust the evidence, constrain the automation, and keep people accountable for material decisions."
```

## Optional instruction after the first draft

```text
Now reduce every slide to presentation-sized text, check all technical claims against the supplied facts, keep the synthetic-data label visible on slides 5-10, and make the architecture and incident diagrams understandable without speaker notes.
```

## Related

- [Classroom demo guide](CLASSROOM_DEMO.md)
- [Project overview](PROJECT_OVERVIEW.md)
- [Technical reference](TECHNICAL_REFERENCE.md)
