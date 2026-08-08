import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.core import config
from app.core.database import engine
from app.llm.client import get_llm_client


def test_llm_enabled_without_key_uses_rule(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    monkeypatch.setenv("ZHIXUEHUAN_LLM_ENABLED", "true")
    monkeypatch.delenv("ZHIXUEHUAN_LLM_API_KEY", raising=False)
    config.get_settings.cache_clear()
    assert get_llm_client() is None

    user = client.post("/api/users", json={"name": "缺key用户"}).json()
    response = client.post(
        "/api/courses/from-text",
        json={
            "user_id": user["id"],
            "course_title": "高等数学",
            "goal": "复习极限",
            "start_date": "2026-07-11",
            "end_date": "2026-07-13",
            "daily_minutes": 40,
            "material_text": "极限定义。重要极限。无穷小比较。",
        },
    )
    assert response.status_code == 200
    assert {trace["execution_mode"] for trace in response.json()["trace"]} == {"rule"}
    config.get_settings.cache_clear()


def test_settings_can_load_local_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "ZHIXUEHUAN_LLM_ENABLED=true",
                "ZHIXUEHUAN_LLM_PROVIDER=test-provider",
                "ZHIXUEHUAN_LLM_MODEL=test-model",
                "ZHIXUEHUAN_LLM_API_KEY=test-key",
                "ZHIXUEHUAN_LLM_BASE_URL=https://llm.example.test/v1",
                "ZHIXUEHUAN_LLM_TIMEOUT_SECONDS=30",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    config.get_settings.cache_clear()
    settings = config.get_settings()
    assert settings.llm_enabled is True
    assert settings.llm_provider == "test-provider"
    assert settings.llm_model == "test-model"
    assert settings.llm_api_key == "test-key"
    assert settings.llm_base_url_safe == "llm.example.test"
    assert settings.llm_timeout_seconds == 30
    config.get_settings.cache_clear()


def test_api_key_not_in_error_response(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    secret = "sk-test-secret-should-not-leak"
    monkeypatch.setenv("ZHIXUEHUAN_LLM_API_KEY", secret)
    response = client.post("/api/courses/from-text", json={"bad": "payload"})
    assert response.status_code == 422
    assert secret not in response.text


def test_trace_observation_fields_exist(client: TestClient) -> None:
    user = client.post("/api/users", json={"name": "trace字段用户"}).json()
    response = client.post(
        "/api/courses/from-text",
        json={
            "user_id": user["id"],
            "course_title": "高等数学",
            "goal": "复习极限",
            "start_date": "2026-07-11",
            "end_date": "2026-07-13",
            "daily_minutes": 40,
            "material_text": "极限定义。重要极限。无穷小比较。",
        },
    )
    trace = response.json()["trace"][0]
    assert "execution_mode" in trace
    assert "request_id" in trace
    assert "retry_count" in trace
    assert "input_char_count" in trace
    assert "output_char_count" in trace


def test_migration_columns_exist_after_create_tables() -> None:
    inspector = inspect(engine)
    trace_columns = {column["name"] for column in inspector.get_columns("agent_traces")}
    exercise_columns = {column["name"] for column in inspector.get_columns("exercises")}
    mastery_columns = {column["name"] for column in inspector.get_columns("mastery_records")}
    answer_columns = {column["name"] for column in inspector.get_columns("submission_answers")}
    assert {
        "task_id",
        "execution_mode",
        "provider",
        "model_name",
        "fallback_reason",
        "request_id",
        "retry_count",
        "input_char_count",
        "output_char_count",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    } <= trace_columns
    assert "question_type" in exercise_columns
    assert {"user_id", "score", "confidence", "updated_at"} <= mastery_columns
    assert "evaluation_reason" in answer_columns


def test_cors_config_allows_localhost_origin(client: TestClient) -> None:
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers.get("access-control-allow-credentials") != "true"


def test_unified_error_response_format(client: TestClient) -> None:
    response = client.get("/api/plans/999999")
    assert response.status_code == 404
    data = response.json()
    assert set(data) == {"error"}
    assert data["error"]["code"] == "NOT_FOUND"
    assert data["error"]["message"] == "plan not found"
    assert data["error"]["details"] == {}


def test_api_contract_file_exists_and_mentions_main_routes() -> None:
    content = Path("docs/api_contract.md").read_text(encoding="utf-8")
    for route in [
        "POST /api/users",
        "POST /api/courses/from-text",
        "POST /api/courses/from-file",
        "GET /api/plans/{plan_id}",
        "GET /api/plans/{plan_id}/today",
        "POST /api/tasks/{task_id}/submit",
        "GET /api/plans/{plan_id}/trace",
        "GET /health",
    ]:
        assert route in content
    assert "standard_answer" in content


def test_env_example_has_placeholders_and_gitignore_excludes_env() -> None:
    env_example = Path(".env.example").read_text(encoding="utf-8")
    gitignore = Path(".gitignore").read_text(encoding="utf-8")
    assert "replace-with-your-api-key" in env_example
    assert {".env", "demo/.env", ".env.*", "*.key", "*.pem"} <= set(gitignore.splitlines())
    assert not Path(".env").exists() or "replace-with-your-api-key" not in Path(".env").read_text(encoding="utf-8")


def test_default_pytest_does_not_enable_live_llm() -> None:
    assert "PYTEST_CURRENT_TEST" in os.environ
