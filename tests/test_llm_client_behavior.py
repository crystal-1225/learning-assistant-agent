import json

import httpx
import pytest

from app.core.config import Settings
from app.llm.client import OpenAICompatibleLLMClient
from app.llm.exceptions import LLMInvalidResponseError, LLMRequestError
from app.llm.schemas import LLMGoalAnalysis


class FakeResponse:
    def __init__(self, payload: dict, status_error: Exception | None = None) -> None:
        self.payload = payload
        self.status_error = status_error

    def raise_for_status(self) -> None:
        if self.status_error:
            raise self.status_error

    def json(self) -> dict:
        return self.payload


class FakeHttpClient:
    calls = 0
    payloads: list[dict] = []
    responses: list[FakeResponse | Exception] = []
    client_kwargs: list[dict] = []

    def __init__(self, timeout: float, trust_env: bool) -> None:
        self.timeout = timeout
        self.trust_env = trust_env
        FakeHttpClient.client_kwargs.append({"timeout": timeout, "trust_env": trust_env})

    def __enter__(self) -> "FakeHttpClient":
        return self

    def __exit__(self, *args) -> None:
        return None

    def post(self, url: str, headers: dict, json: dict):
        FakeHttpClient.calls += 1
        FakeHttpClient.payloads.append({"url": url, "headers": headers, "json": json})
        response = FakeHttpClient.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def settings() -> Settings:
    return Settings(
        llm_enabled=True,
        llm_api_key="sk-secret",
        llm_model="fake-model",
        llm_base_url="https://example.test/v1",
        llm_max_retries=2,
        llm_timeout_seconds=1,
    )


def valid_payload() -> dict:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "objective": "复习",
                            "target_topics": ["极限"],
                            "constraints": ["3天"],
                            "study_style": "练习",
                            "summary": "摘要",
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


def test_retry_count_does_not_exceed_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm import client as client_module

    FakeHttpClient.calls = 0
    FakeHttpClient.client_kwargs = []
    FakeHttpClient.responses = [httpx.ConnectError("boom"), FakeResponse(valid_payload())]
    monkeypatch.setattr(client_module.httpx, "Client", FakeHttpClient)
    llm = OpenAICompatibleLLMClient(settings())
    result = llm.generate_structured(prompt="hello", response_model=LLMGoalAnalysis)
    assert result.summary == "摘要"
    assert FakeHttpClient.calls == 2
    assert llm.last_call_metadata is not None
    assert llm.last_call_metadata.retry_count == 1
    assert llm.last_call_metadata.total_tokens == 30
    assert "sk-secret" not in str(llm.last_call_metadata)
    assert all(kwargs["trust_env"] is False for kwargs in FakeHttpClient.client_kwargs)


def test_consecutive_model_failures_raise_without_infinite_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm import client as client_module

    FakeHttpClient.calls = 0
    FakeHttpClient.responses = [httpx.ConnectError("boom"), httpx.ConnectError("boom")]
    monkeypatch.setattr(client_module.httpx, "Client", FakeHttpClient)
    llm = OpenAICompatibleLLMClient(settings())
    with pytest.raises(LLMRequestError):
        llm.generate_structured(prompt="hello", response_model=LLMGoalAnalysis)
    assert FakeHttpClient.calls == 2


@pytest.mark.parametrize("status_code", [401, 403])
def test_auth_failure_does_not_retry_or_leak_api_key(monkeypatch: pytest.MonkeyPatch, status_code: int) -> None:
    from app.llm import client as client_module

    secret = "sk-secret"
    auth_error = httpx.HTTPStatusError(
        "authorization failed",
        request=httpx.Request("POST", "https://example.test/v1/chat/completions"),
        response=httpx.Response(status_code),
    )
    FakeHttpClient.calls = 0
    FakeHttpClient.responses = [FakeResponse({}, status_error=auth_error)]
    monkeypatch.setattr(client_module.httpx, "Client", FakeHttpClient)
    llm = OpenAICompatibleLLMClient(settings())

    with pytest.raises(LLMRequestError) as exc:
        llm.generate_structured(prompt="hello", response_model=LLMGoalAnalysis)

    assert FakeHttpClient.calls == 1
    assert secret not in str(exc.value)
    assert secret not in str(llm.last_call_metadata)


def test_rate_limit_and_timeout_retries_are_finite(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm import client as client_module

    rate_limited = httpx.HTTPStatusError(
        "rate limited",
        request=httpx.Request("POST", "https://example.test/v1/chat/completions"),
        response=httpx.Response(429),
    )
    FakeHttpClient.calls = 0
    FakeHttpClient.responses = [FakeResponse({}, status_error=rate_limited), httpx.TimeoutException("timeout")]
    monkeypatch.setattr(client_module.httpx, "Client", FakeHttpClient)
    llm = OpenAICompatibleLLMClient(settings())

    with pytest.raises(LLMRequestError):
        llm.generate_structured(prompt="hello", response_model=LLMGoalAnalysis)

    assert FakeHttpClient.calls == 2
    assert llm.last_call_metadata is not None
    assert llm.last_call_metadata.retry_count == 1


def test_too_long_prompt_is_rejected_before_request(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm import client as client_module

    limited = Settings(
        llm_enabled=True,
        llm_api_key="sk-secret",
        llm_model="fake-model",
        llm_base_url="https://example.test/v1",
        llm_max_input_chars=4,
    )
    FakeHttpClient.calls = 0
    FakeHttpClient.responses = []
    monkeypatch.setattr(client_module.httpx, "Client", FakeHttpClient)
    llm = OpenAICompatibleLLMClient(limited)

    with pytest.raises(LLMInvalidResponseError, match="max input length"):
        llm.generate_structured(prompt="hello", response_model=LLMGoalAnalysis)

    assert FakeHttpClient.calls == 0


def test_invalid_json_is_rejected_without_exposing_response_body(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm import client as client_module

    FakeHttpClient.calls = 0
    FakeHttpClient.responses = [FakeResponse({"choices": [{"message": {"content": "not-json-secret-body"}}]})]
    monkeypatch.setattr(client_module.httpx, "Client", FakeHttpClient)
    llm = OpenAICompatibleLLMClient(settings())

    with pytest.raises(LLMInvalidResponseError) as exc:
        llm.generate_structured(prompt="hello", response_model=LLMGoalAnalysis)

    assert FakeHttpClient.calls == 1
    assert "not-json-secret-body" not in str(exc.value)


def test_too_long_model_output_is_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm import client as client_module

    custom = Settings(
        llm_enabled=True,
        llm_api_key="sk-secret",
        llm_model="fake-model",
        llm_base_url="https://example.test/v1",
        llm_max_retries=2,
        llm_timeout_seconds=1,
        llm_max_output_chars=5,
    )
    FakeHttpClient.calls = 0
    FakeHttpClient.responses = [FakeResponse(valid_payload())]
    monkeypatch.setattr(client_module.httpx, "Client", FakeHttpClient)
    llm = OpenAICompatibleLLMClient(custom)
    with pytest.raises(LLMInvalidResponseError):
        llm.generate_structured(prompt="hello", response_model=LLMGoalAnalysis)
