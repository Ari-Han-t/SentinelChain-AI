import json

import httpx
import pytest

from app.config import Settings
from app.guidance import guidance_for
import app.guidance as guidance_module


def _build_settings(**overrides) -> Settings:
    base = {
        "_env_file": None,
        "ai_provider": None,
        "groq_api_key": None,
        "groq_model": "llama-test",
        "gemini_api_key": None,
        "gemini_model": "gemini-test",
        "ai_timeout_seconds": 5,
        "ai_max_tokens": 900,
        "azure_ai_foundry_enabled": False,
    }
    base.update(overrides)
    return Settings(**base)


def _chat_response(content: str, finish_reason: str = "stop") -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": finish_reason}]})


def _valid_body(evidence_ids: list[int]) -> str:
    return json.dumps({
        "status_summary": "Remote summary",
        "rationale": "Remote rationale",
        "evidence_ids": evidence_ids,
        "confidence": 0.75,
        "no_action_required": False,
        "next_check_hours": 6,
        "actions": [{
            "title": "Escalate shipment",
            "reason": "Validate the disputed evidence before planning.",
            "owner_role": "manager",
            "urgency": "high",
            "expected_impact": "Restores trusted state.",
            "due_hours": 4,
        }],
    })


def _node() -> dict:
    return {"id": 7, "key": "supplier", "name": "Supplier", "status": "at_risk", "owner_role": "manager"}


def _evidence() -> list[dict]:
    return [{"id": 101}, {"id": 102}, {"id": 103}]


def _org() -> dict:
    return {"id": 1, "name": "Org"}


def _use_settings(monkeypatch, cfg: Settings):
    monkeypatch.setattr(guidance_module, "settings", cfg)


def _call_with(monkeypatch, cfg: Settings, handler, *, evidence=None, calls=None):
    _use_settings(monkeypatch, cfg)
    if calls is None:
        calls = []

    def transport(url, *, headers, json, timeout) -> httpx.Response:
        request = httpx.Request("POST", url, headers=headers, json=json)
        request.extensions["timeout"] = httpx.Timeout(timeout).as_dict()
        calls.append(request)
        response = handler(request)
        response.request = request
        return response

    monkeypatch.setattr(guidance_module.httpx, "post", transport)
    result = guidance_for(_node(), _evidence() if evidence is None else evidence, _org())
    request = calls[0] if calls else None
    body = json.loads(request.content) if request is not None else None
    return result, (request, body)


def test_settings_guidance_provider_resolution():
    assert _build_settings(ai_provider=None).guidance_provider == "deterministic"
    assert _build_settings(ai_provider="groq").guidance_provider == "groq"
    assert _build_settings(ai_provider="gemini").guidance_provider == "gemini"
    assert _build_settings(ai_provider="deterministic").guidance_provider == "deterministic"
    azure = {
        "azure_ai_foundry_endpoint": "https://legacy.example/openai/deployments/x",
        "azure_ai_foundry_api_key": "legacy-key",
        "azure_ai_foundry_model": "legacy-model",
    }
    assert _build_settings(ai_provider="azure-ai-foundry", **azure).guidance_provider == "azure-ai-foundry"
    legacy = _build_settings(ai_provider=None, azure_ai_foundry_enabled=True, **azure)
    assert legacy.guidance_provider == "azure-ai-foundry"
    assert _build_settings(ai_provider="deterministic", azure_ai_foundry_enabled=True).guidance_provider == "deterministic"


def test_explicit_provider_overrides_legacy_azure(monkeypatch):
    cfg = _build_settings(
        ai_provider="groq",
        groq_api_key="gsk-test",
        azure_ai_foundry_enabled=True,
        azure_ai_foundry_endpoint="https://legacy.example/openai/deployments/x",
        azure_ai_foundry_api_key="legacy-key",
        azure_ai_foundry_model="legacy-model",
    )
    (provider, payload), (request, body) = _call_with(
        monkeypatch, cfg, lambda request: _chat_response(_valid_body([101, 102]))
    )
    assert provider == "groq"
    assert str(request.url).startswith("https://api.groq.com/openai/v1/chat/completions")


def test_none_provider_preserves_legacy_azure(monkeypatch):
    cfg = _build_settings(
        ai_provider=None,
        azure_ai_foundry_enabled=True,
        azure_ai_foundry_endpoint="https://legacy.example/openai/deployments/x",
        azure_ai_foundry_api_key="legacy-key",
        azure_ai_foundry_model="legacy-model",
    )
    (provider, payload), (request, body) = _call_with(
        monkeypatch, cfg, lambda request: httpx.Response(200, json={"output_text": _valid_body([101])})
    )
    assert provider == "azure-ai-foundry"
    assert str(request.url) == "https://legacy.example/openai/deployments/x/responses"
    assert "Authorization" not in request.headers or "Bearer" in request.headers["Authorization"]
    assert request.headers["api-key"] == "legacy-key"
    assert json.loads(body["input"])["node"]["key"] == "supplier"


def test_deterministic_provider_makes_no_http_call(monkeypatch):
    cfg = _build_settings(ai_provider="deterministic", groq_api_key="gsk-test", gemini_api_key="gemini-test")

    def explode(request):
        raise AssertionError("deterministic provider must not issue HTTP requests")

    calls = []
    (provider, payload), (request, body) = _call_with(monkeypatch, cfg, explode, calls=calls)
    assert calls == []
    assert request is None
    assert body is None
    assert provider == "deterministic"
    assert payload.no_action_required is False
    assert payload.actions


def test_groq_chat_completions_request_shape(monkeypatch):
    cfg = _build_settings(ai_provider="groq", groq_api_key="gsk-test", groq_model="llama-test", ai_timeout_seconds=9, ai_max_tokens=777)
    (provider, payload), (request, body) = _call_with(
        monkeypatch, cfg, lambda request: _chat_response(_valid_body([101, 102, 103]))
    )
    assert provider == "groq"
    assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer gsk-test"
    assert "api-key" not in request.headers
    assert body["model"] == "llama-test"
    assert body["max_completion_tokens"] == 777
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][-1]["role"] == "user"
    assert len(body["messages"]) == 2
    context = json.loads(body["messages"][-1]["content"])
    assert context["evidence"] == _evidence()
    assert "required_shape" in context
    assert payload.evidence_ids == [101, 102, 103]
    assert payload.actions[0].title == "Escalate shipment"
    assert request.extensions["timeout"]["read"] == 9


def test_gemini_success_uses_chat_completions_and_avoids_groq(monkeypatch):
    cfg = _build_settings(ai_provider="gemini", gemini_api_key="gemini-test", groq_api_key="gsk-test")
    calls = []
    (provider, payload), (request, body) = _call_with(
        monkeypatch, cfg, lambda request: _chat_response(_valid_body([101])), calls=calls
    )
    assert provider == "gemini"
    assert len(calls) == 1
    assert str(request.url) == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert request.headers["Authorization"] == "Bearer gemini-test"
    assert "api-key" not in request.headers
    assert body["model"] == "gemini-test"
    assert body["response_format"] == {"type": "json_object"}
    assert body["max_completion_tokens"] == 900
    assert payload.status_summary == "Remote summary"
    assert payload.evidence_ids == [101]


def test_chat_evidence_below_limit_is_preserved(monkeypatch):
    cfg = _build_settings(ai_provider="groq", groq_api_key="gsk-test")
    (provider, payload), (request, body) = _call_with(
        monkeypatch, cfg, lambda request: _chat_response(_valid_body([101]))
    )
    context = json.loads(body["messages"][-1]["content"])
    assert provider == "groq"
    assert context["evidence"] == _evidence()
    assert len(context["evidence"]) == 3


def test_chat_payload_with_twenty_plus_evidence_sends_first_twenty(monkeypatch):
    cfg = _build_settings(ai_provider="groq", groq_api_key="gsk-test")
    evidence = [{"id": i} for i in range(1, 31)]
    (provider, payload), (request, body) = _call_with(
        monkeypatch, cfg, lambda request: _chat_response(_valid_body([1])), evidence=evidence
    )
    context = json.loads(body["messages"][-1]["content"])
    assert provider == "groq"
    assert [item["id"] for item in context["evidence"]] == list(range(1, 21))


def test_missing_api_key_falls_back_deterministic_without_http(monkeypatch):
    def explode(request):
        raise AssertionError("missing key must not issue HTTP requests")

    cfg = _build_settings(ai_provider="groq", groq_api_key=None)
    calls = []
    (provider, payload), (request, body) = _call_with(monkeypatch, cfg, explode, calls=calls)
    assert calls == []
    assert request is None
    assert body is None
    assert provider == "deterministic"
    cfg = _build_settings(ai_provider="gemini", gemini_api_key=None)
    calls = []
    (provider, payload), (request, body) = _call_with(monkeypatch, cfg, explode, calls=calls)
    assert calls == []
    assert request is None
    assert body is None
    assert provider == "deterministic"


@pytest.mark.parametrize("failure", ["timeout", 401, 429, "invalid_json", "invalid_schema", "invalid_citation", "truncated", "invalid_envelope"])
def test_gemini_failure_falls_back_to_groq(monkeypatch, failure):
    cfg = _build_settings(ai_provider="gemini", gemini_api_key="gemini-test", groq_api_key="gsk-test")
    calls = []

    def handler(request):
        if request.url.host == "api.groq.com":
            return _chat_response(_valid_body([102]))
        assert request.url.host == "generativelanguage.googleapis.com"
        if failure == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if isinstance(failure, int):
            return httpx.Response(failure, json={"error": "unavailable"})
        if failure == "invalid_schema":
            return _chat_response('{"status_summary": "Missing fields"}')
        if failure == "invalid_citation":
            return _chat_response(_valid_body([999]))
        if failure == "truncated":
            return _chat_response(_valid_body([101]), finish_reason="length")
        if failure == "invalid_envelope":
            return httpx.Response(200, json={"choices": []})
        return _chat_response("not json")

    (provider, payload), _ = _call_with(monkeypatch, cfg, handler, calls=calls)
    assert [request.url.host for request in calls] == ["generativelanguage.googleapis.com", "api.groq.com"]
    assert calls[1].headers["Authorization"] == "Bearer gsk-test"
    assert json.loads(calls[1].content)["model"] == "llama-test"
    assert provider == "groq"
    assert payload.status_summary == "Remote summary"
    assert payload.evidence_ids == [102]


@pytest.mark.parametrize("key", [None, "", "   "])
def test_missing_gemini_key_uses_groq(monkeypatch, key):
    cfg = _build_settings(ai_provider="gemini", gemini_api_key=key, groq_api_key="gsk-test")
    calls = []
    (provider, payload), _ = _call_with(
        monkeypatch, cfg, lambda request: _chat_response(_valid_body([103])), calls=calls
    )
    assert [request.url.host for request in calls] == ["api.groq.com"]
    assert provider == "groq"
    assert payload.evidence_ids == [103]


@pytest.mark.parametrize("failure", ["timeout", 401, 429, "invalid_response"])
def test_gemini_and_groq_failure_uses_deterministic(monkeypatch, failure):
    cfg = _build_settings(ai_provider="gemini", gemini_api_key="gemini-test", groq_api_key="gsk-test")
    calls = []

    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if isinstance(failure, int):
            return httpx.Response(failure, json={"error": "unavailable"})
        return _chat_response("not json")

    (provider, payload), _ = _call_with(monkeypatch, cfg, handler, calls=calls)
    assert [request.url.host for request in calls] == ["generativelanguage.googleapis.com", "api.groq.com"]
    assert provider == "deterministic"
    assert payload == guidance_module.deterministic_guidance(_node(), _evidence())


def test_invalid_json_falls_back_deterministic(monkeypatch):
    cfg = _build_settings(ai_provider="groq", groq_api_key="gsk-test")
    (provider, payload), (request, body) = _call_with(
        monkeypatch, cfg, lambda request: _chat_response("this is not json")
    )
    assert provider == "deterministic"
    (provider, payload), (request, body) = _call_with(
        monkeypatch, cfg, lambda request: _chat_response("prefix ```json\n{bad}\n``` suffix")
    )
    assert provider == "deterministic"


def test_unknown_evidence_citation_falls_back_deterministic(monkeypatch):
    cfg = _build_settings(ai_provider="groq", groq_api_key="gsk-test")
    (provider, payload), (request, body) = _call_with(
        monkeypatch, cfg, lambda request: _chat_response(_valid_body([101, 999]))
    )
    assert provider == "deterministic"


def test_no_action_required_clears_actions(monkeypatch):
    cfg = _build_settings(ai_provider="groq", groq_api_key="gsk-test")
    body = _valid_body([101])
    parsed = json.loads(body)
    parsed["no_action_required"] = True
    (provider, payload), (request, sent) = _call_with(
        monkeypatch, cfg, lambda request: _chat_response(json.dumps(parsed))
    )
    assert provider == "groq"
    assert payload.no_action_required is True
    assert payload.actions == []


def test_timeout_falls_back_deterministic(monkeypatch):
    cfg = _build_settings(ai_provider="groq", groq_api_key="gsk-test", ai_timeout_seconds=2)

    def handler(request):
        raise httpx.ReadTimeout("timed out")

    (provider, payload), (request, body) = _call_with(monkeypatch, cfg, handler)
    assert provider == "deterministic"
    assert payload.actions


@pytest.mark.parametrize("status", [401, 429, 500])
def test_http_error_status_falls_back_deterministic(monkeypatch, status):
    cfg = _build_settings(ai_provider="groq", groq_api_key="gsk-test")
    (provider, payload), (request, body) = _call_with(
        monkeypatch, cfg, lambda request: httpx.Response(status, json={"error": {"message": "boom"}})
    )
    assert provider == "deterministic"


def test_truncated_finish_reason_falls_back_deterministic(monkeypatch):
    cfg = _build_settings(ai_provider="groq", groq_api_key="gsk-test")
    fragment = json.dumps({"status_summary": "Cut off"})
    (provider, payload), (request, body) = _call_with(
        monkeypatch, cfg, lambda request: _chat_response(fragment, finish_reason="length")
    )
    assert provider == "deterministic"


def test_schema_violation_falls_back_deterministic(monkeypatch):
    cfg = _build_settings(ai_provider="groq", groq_api_key="gsk-test")
    bad = json.dumps({"status_summary": "Missing required fields"})
    (provider, payload), (request, body) = _call_with(
        monkeypatch, cfg, lambda request: _chat_response(bad)
    )
    assert provider == "deterministic"


def test_failure_logs_only_exception_class(monkeypatch, caplog):
    cfg = _build_settings(ai_provider="groq", groq_api_key="gsk-secret")
    secret_token = "gsk-secret"

    def handler(request):
        raise httpx.HTTPStatusError(
            "secret detail leaked", request=request, response=httpx.Response(401, json={"error": {"message": "bad key gsk-secret"}})
        )

    with caplog.at_level("WARNING", logger="app.guidance"):
        (provider, payload), (request, body) = _call_with(monkeypatch, cfg, handler)
    assert provider == "deterministic"
    records = [record for record in caplog.records if record.levelname == "WARNING"]
    assert records
    assert secret_token not in caplog.text
    assert "HTTPStatusError" in caplog.text


def test_graph_inspector_produces_cited_advisory_action(client, auth):
    headers = auth("analyst")
    graph = client.get("/supply-chain", headers=headers)
    assert graph.status_code == 200
    supplier = next(node for node in graph.json()["nodes"] if node["key"] == "supplier")

    inspector = client.get(f"/nodes/{supplier['id']}/inspector", headers=headers)
    assert inspector.status_code == 200
    guidance = inspector.json()["guidance"]
    assert guidance["provider"] == "deterministic"
    assert guidance["no_action_required"] is False
    assert guidance["evidence_ids"]
    assert guidance["actions"][0]["status"] == "pending"


def test_manual_conflict_blocks_node_and_preserves_both_sources(client, auth):
    analyst = auth("analyst")
    event = {
        "node_key": "logistics",
        "event_type": "shipment.status",
        "summary": "Shipment remains in transit",
        "payload": {"state": "in_transit"},
        "external_id": "erp-shipment-42",
        "conflict_key": "shipment-42:state",
        "confidence": 1,
    }
    first = client.post("/events", json=event, headers=analyst)
    duplicate = client.post("/events", json=event, headers=analyst)
    assert first.status_code == 200
    assert duplicate.json()["id"] == first.json()["id"]

    node_id = first.json()["node_id"]
    manual = client.post(
        f"/nodes/{node_id}/manual-events",
        json={**event, "external_id": None, "summary": "Shipment arrived at dock", "payload": {"state": "arrived"}},
        headers=analyst,
    )
    assert manual.status_code == 200
    assert manual.json()["status"] == "disputed"

    inspector = client.get(f"/nodes/{node_id}/inspector", headers=analyst).json()
    assert inspector["node"]["status"] == "disputed"
    assert sum(item["status"] == "disputed" for item in inspector["evidence"]) == 2
    assert "Reconcile" in inspector["guidance"]["actions"][0]["title"]


def test_action_requires_manager_and_expected_pending_state(client, auth):
    analyst = auth("analyst")
    supplier = next(node for node in client.get("/supply-chain", headers=analyst).json()["nodes"] if node["key"] == "supplier")
    action_id = client.get(f"/nodes/{supplier['id']}/inspector", headers=analyst).json()["guidance"]["actions"][0]["id"]
    body = {"decision": "approved", "expected_status": "pending", "note": "Expedite approved"}
    assert client.post(f"/actions/{action_id}/decision", json=body, headers=analyst).status_code == 403

    manager = auth("manager")
    approved = client.post(f"/actions/{action_id}/decision", json=body, headers=manager)
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert client.post(f"/actions/{action_id}/decision", json=body, headers=manager).status_code == 409
