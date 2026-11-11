"""Tests for the AWS showcase deployment additions: proxy-aware rate limiting,
showcase secret validation and the Bedrock guidance provider."""

from types import SimpleNamespace

import pytest

from app import guidance, main
from app.config import Settings


def _request(peer: str, xff: str | None = None):
    headers = {"x-forwarded-for": xff} if xff else {}
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


def test_client_key_ignores_forwarded_header_without_trusted_proxy(monkeypatch):
    monkeypatch.setattr(main.settings, "trusted_proxy_hops", 0)
    assert main._client_key(_request("10.0.0.5", "1.2.3.4")) == "10.0.0.5"


def test_client_key_uses_proxy_appended_hop_and_resists_spoofing(monkeypatch):
    monkeypatch.setattr(main.settings, "trusted_proxy_hops", 1)
    # Client tried to spoof "6.6.6.6"; nginx appended the real address last.
    assert main._client_key(_request("172.18.0.3", "6.6.6.6, 203.0.113.9")) == "203.0.113.9"
    # Missing header falls back to the socket peer.
    assert main._client_key(_request("172.18.0.3")) == "172.18.0.3"


def test_showcase_requires_strong_distinct_secrets():
    with pytest.raises(ValueError):
        Settings(environment="showcase", jwt_secret="development-jwt-secret")
    strong = dict(
        jwt_secret="a" * 40,
        import_hmac_secret="b" * 40,
        field_encryption_key="c" * 40,
    )
    settings = Settings(environment="showcase", demo_mode=True, seed_demo_data=True, **strong)
    assert settings.demo_mode is True
    with pytest.raises(ValueError):
        Settings(environment="showcase", jwt_secret="x" * 40, import_hmac_secret="x" * 40, field_encryption_key="y" * 40)


def test_bedrock_guidance_is_schema_validated(monkeypatch):
    node = {"id": 1, "name": "Warehouse", "status": "at_risk"}
    evidence = [{"id": 7, "summary": "stock below reorder point"}]
    valid = (
        '{"status_summary":"Stock is low","rationale":"Evidence 7 shows depletion","evidence_ids":[7],'
        '"confidence":0.8,"no_action_required":false,"next_check_hours":4,"actions":[]}'
    )
    monkeypatch.setattr(guidance, "_bedrock_converse", lambda system, user: valid)
    result = guidance.remote_guidance("bedrock", node, evidence, {"name": "Demo"})
    assert result is not None and result.evidence_ids == [7]

    # A model that cites evidence it was never given is rejected and falls back.
    monkeypatch.setattr(guidance, "_bedrock_converse", lambda system, user: valid.replace("[7]", "[99]"))
    assert guidance.remote_guidance("bedrock", node, evidence, {"name": "Demo"}) is None

    # Truncated / non-final generations are treated as unavailable.
    monkeypatch.setattr(guidance, "_bedrock_converse", lambda system, user: None)
    assert guidance.remote_guidance("bedrock", node, evidence, {"name": "Demo"}) is None
