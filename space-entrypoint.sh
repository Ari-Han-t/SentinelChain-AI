#!/bin/sh
# Generate strong per-boot secrets unless provided as Space secrets. The demo database is
# re-seeded from synthetic data on each boot, so rotating secrets on restart is harmless
# (it simply signs everyone out).
set -eu
gen() { python -c "import secrets; print(secrets.token_hex(32))"; }
export JWT_SECRET="${JWT_SECRET:-$(gen)}"
export IMPORT_HMAC_SECRET="${IMPORT_HMAC_SECRET:-$(gen)}"
export FIELD_ENCRYPTION_KEY="${FIELD_ENCRYPTION_KEY:-$(gen)}"
# Without a GROQ_API_KEY secret, guidance uses the deterministic engine.
if [ -z "${GROQ_API_KEY:-}" ]; then export AI_PROVIDER=deterministic; fi
exec uvicorn app.space_app:app --host 0.0.0.0 --port "${PORT:-7860}" --proxy-headers --forwarded-allow-ips '*'
