# Project overview

## What problem does SentinelChain solve?

A supply chain depends on data from many places: sales systems, suppliers, purchase orders, warehouses, production lines, logistics partners, and employees. A wrong or malicious record can cause the business to order too much, run out of a critical component, delay customers, or make a decision using untrusted information.

Most dashboards show numbers. SentinelChain focuses on a harder question:

> Can we trust the evidence behind the recommendation, and who is allowed to act on it?

## The proposed solution

SentinelChain AI is a web-based control tower for an industrial manufacturer. It:

1. Models the supply chain as connected operational stages.
2. Collects system events and structured human updates as evidence.
3. preserves conflicting reports instead of silently overwriting one.
4. Generates guidance tied to specific evidence records.
5. Keeps purchase and operational actions pending until an authorized human decides.
6. Records important events in a tamper-evident audit chain.
7. Uses anomaly checks to quarantine suspicious sales or supplier inputs before they influence forecasts.

The AI component is advisory. Azure AI Foundry can generate structured guidance when configured. A deterministic rules-based provider keeps the monitoring flow usable when Foundry is disabled or unavailable.

## The classroom scenario

The fictional company, **Sentinel Industrial Systems**, manufactures industrial automation and safety control panels in Bengaluru.

Its current situation is deliberately interesting:

- Hospital automation orders caused a 42% week-over-week rise in Safety Relay demand.
- Safety Relay stock is only 38 units while supplier lead time increased to 17 days.
- A supplier says 480 units were dispatched, but warehouse evidence expects only 320.
- A different supplier presented an untrusted TLS certificate and was blocked.
- Port congestion added four days to a critical shipment.
- A power-module shipment exceeded its temperature limit.
- Production can re-sequence work to protect 84 priority panel completions.
- Expedited air freight is available, but a procurement manager must approve it.

This creates a useful story: demand changes, evidence conflicts, cyber controls block suspicious input, the system proposes mitigations, and people retain decision authority.

## What data is available?

The rich loader adds:

| Data | Volume | Why it matters |
|---|---:|---|
| Products | 12 SKUs | Mix of healthy, watch, and critical inventory positions |
| Sales | 365 daily observations per SKU | Enough history for forecasting and seasonal patterns |
| Suppliers | 8 | Different reliability, lead time, defect, and price-risk profiles |
| Forecasts | 12 | Current demand estimates with error metrics and feature explanations |
| Recommendations | 12 | Reorder point, safety stock, EOQ, quantity, risk, and decision state |
| Scenario evidence | 48 records | Recent facts across every visible supply-chain stage |
| Alerts | 12 scenario alerts | Availability, integrity, authentication, logistics, quality, and customer risk |
| Quarantined rows | 5 | Examples of anomalous or conflicting inputs kept out of trusted data |
| Action proposals | 10 scenario actions | Pending, approved, and rejected decisions with reasons and impact |

The original small seed remains, so the live database may contain one extra default alert, evidence item, or action.

## How information moves through the system

```text
Supplier / ERP / CRM / warehouse / human update
                       |
                       v
       Authentication + schema validation
                       |
            +----------+-----------+
            |                      |
       trusted input          suspicious input
            |                      |
            v                      v
      evidence record      quarantine + alert
            |
            v
     guidance with cited evidence
            |
            v
       pending action
            |
            v
 authorized human approves or rejects
            |
            v
      tamper-evident audit event
```

## The four user roles

| Role | Main responsibility |
|---|---|
| Administrator | Configure the demo, inspect all stages, run integrity drills, and verify audit history |
| Inventory analyst | Add evidence, inspect risk, train forecasts, and generate recommendations |
| Procurement manager | Approve or reject material actions and recommendations |
| Auditor | Read the audit history and verify the hash chain without operational privileges |

This separation demonstrates least privilege: a person can see or propose something without automatically gaining permission to approve it.

## Security ideas demonstrated

- **Authentication:** short-lived JSON Web Tokens identify the current user.
- **Authorization:** role checks restrict imports, attacks, approvals, and audit access.
- **Password protection:** passwords are hashed with Argon2.
- **Confidentiality:** supplier contacts are encrypted with AES-GCM.
- **Input integrity:** CSV files require an HMAC signature.
- **Anomaly containment:** invalid and extreme records are quarantined before forecasting.
- **Evidence integrity:** conflicting source claims are preserved and marked disputed.
- **Decision safety:** material actions require explicit approval using an expected pending state.
- **Audit integrity:** each audit event includes the previous event's hash.
- **LLM safety:** evidence is treated as untrusted data, responses must match a schema, and cited IDs must exist.

## What this project does not claim

This is an academic prototype using synthetic data. It does not place real purchase orders, connect to a live ERP, prove real-world forecast accuracy, or provide production-grade non-repudiation. The value of the demo is the architecture and security workflow, not a claim that the fictional business metrics are real.

## Next

- Rehearse the [classroom demo](CLASSROOM_DEMO.md).
- Read the [technical reference](TECHNICAL_REFERENCE.md) before taking questions.
