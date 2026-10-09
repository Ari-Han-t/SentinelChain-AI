# SentinelChain AI documentation

Start here if you need to understand or present the project.

| Document | Use it when you need to... |
|---|---|
| [Project overview](PROJECT_OVERVIEW.md) | Explain the problem, solution, users, and end-to-end flow in plain language |
| [Classroom demo guide](CLASSROOM_DEMO.md) | Deliver a 6-8 minute live demonstration and answer likely questions |
| [Technical reference](TECHNICAL_REFERENCE.md) | Explain the architecture, data model, API, security controls, and commands |
| [PPT generation prompt](PPT_PROMPT.md) | Generate a polished 10-slide classroom presentation in an AI presentation tool |

## The 30-second explanation

SentinelChain AI is a security-first supply-chain control tower. It combines demand, supplier, procurement, production, logistics, and customer evidence in one graph. It flags risky or conflicting data, produces evidence-backed guidance, and requires a human to approve material actions. Every important event and decision is linked in a SHA-256 hash chain so later tampering can be detected.

The running classroom scenario is fully synthetic. It contains 12 products, one year of daily sales history, 8 suppliers, forecasts, reorder recommendations, alerts, quarantined inputs, and a supplier disruption story with actionable evidence.

## Run it

```powershell
docker compose up -d
```

Open:

- Application: <http://localhost:5173>
- API documentation: <http://localhost:8000/docs>
- API health: <http://localhost:8000/health>

All demo accounts use `demo1234`. Use `admin@sentinelchain.local` for the full presentation.

## Reload the rich synthetic dataset

The loader is deterministic and idempotent, so a second run does not duplicate its records.

```powershell
docker compose build api
docker compose run --rm api python -m app.demo_data
docker compose up -d api
```

## Suggested reading order

1. Read the [project overview](PROJECT_OVERVIEW.md).
2. Rehearse the [classroom demo](CLASSROOM_DEMO.md).
3. Use the [technical reference](TECHNICAL_REFERENCE.md) for questions.
4. Paste the [PPT prompt](PPT_PROMPT.md) into your preferred slide generator.

