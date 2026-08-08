from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.llm.base import LLMCallMetadata, LLMClient
from app.llm.exceptions import LLMInvalidResponseError
from app.llm.schemas import LLMExerciseSet
from app.models.entities import AgentTrace, DailyTask, Exercise, TaskStatus
from app.tools import exercise_generator


class AutoExerciseLLM(LLMClient):
    provider = "fake-auto-provider"
    model_name = "fake-auto-model"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.last_call_metadata = None

    def generate_structured(
        self,
        *,
        prompt: str,
        response_model: type[BaseModel],
        timeout_seconds: float | None = None,
    ) -> BaseModel:
        self.last_call_metadata = LLMCallMetadata(
            request_id="fake-daily-exercise",
            retry_count=0,
            input_char_count=len(prompt),
            output_char_count=256,
            prompt_tokens=20,
            completion_tokens=30,
            total_tokens=50,
        )
        if self.fail:
            raise LLMInvalidResponseError("invalid daily exercise response")
        assert response_model is LLMExerciseSet
        titles = prompt.rsplit("\n知识点：", maxsplit=1)[-1].split("、")
        first = titles[0]
        second = titles[1] if len(titles) > 1 else first
        difficulty = "medium" if "difficulty 必须全部为 medium" in prompt else "basic"
        return LLMExerciseSet(
            exercises=[
                {
                    "question": f"请简述“{first}”的核心含义。",
                    "standard_answer": f"说明{first}的核心概念。",
                    "explanation": "检查概念理解。",
                    "difficulty": difficulty,
                    "knowledge_point_title": first,
                    "question_type": "short_answer",
                },
                {
                    "question": f"关于“{second}”，以下哪项描述正确？\nA. 忽略条件\nB. 结合定义理解\nC. 只记名称\nD. 无需练习",
                    "standard_answer": "B",
                    "explanation": "检查概念辨析。",
                    "difficulty": difficulty,
                    "knowledge_point_title": second,
                    "question_type": "single_choice",
                },
                {
                    "question": f"判断题：学习“{first}”时需要关注适用条件。\nA. 正确\nB. 错误",
                    "standard_answer": "A",
                    "explanation": "检查条件判断。",
                    "difficulty": difficulty,
                    "knowledge_point_title": first,
                    "question_type": "single_choice",
                },
            ]
        )


def _create_five_day_plan(client: TestClient) -> dict[str, Any]:
    """Create a five-day plan relative to today.

    Dates are derived from ``date.today()`` so the `/today` endpoint always
    treats day 2 as "today's task", regardless of when the tests run.
    """
    user_response = client.post("/api/users", json={"name": "每日练习测试用户"})
    assert user_response.status_code == 200
    today = date.today()
    response = client.post(
        "/api/courses/from-text",
        json={
            "user_id": user_response.json()["id"],
            "course_title": "高等数学",
            "goal": "5天复习极限与导数基础",
            "start_date": (today - timedelta(days=1)).isoformat(),
            "end_date": (today + timedelta(days=3)).isoformat(),
            "daily_minutes": 45,
            "material_text": "极限定义、重要极限、连续性、导数定义、导数应用。",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _select_day(
    db_session: Session,
    plan_id: int,
    day_number: int,
) -> list[DailyTask]:
    tasks = list(
        db_session.scalars(
            select(DailyTask)
            .where(DailyTask.plan_id == plan_id)
            .order_by(DailyTask.task_date, DailyTask.id)
        ).all()
    )
    for task in tasks[: day_number - 1]:
        task.status = TaskStatus.COMPLETED.value
    db_session.commit()
    return tasks


def _auto_trace(db_session: Session, task_id: int) -> AgentTrace:
    return db_session.scalars(
        select(AgentTrace).where(
            AgentTrace.task_id == task_id,
            AgentTrace.tool_name == "exercise_auto_generator",
        )
    ).one()


def test_day2_missing_exercises_are_generated_and_persisted(
    client: TestClient,
    db_session: Session,
) -> None:
    data = _create_five_day_plan(client)
    plan_id = data["plan"]["id"]
    tasks = _select_day(db_session, plan_id, 2)
    day2 = tasks[1]
    assert db_session.scalar(select(func.count(Exercise.id)).where(Exercise.task_id == day2.id)) == 0

    response = client.get(f"/api/plans/{plan_id}/today")

    assert response.status_code == 200, response.text
    assert response.json()["task"]["id"] == day2.id
    assert len(response.json()["task"]["exercises"]) == 3
    assert db_session.scalar(select(func.count(Exercise.id)).where(Exercise.task_id == day2.id)) == 3
    assert _auto_trace(db_session, day2.id).execution_mode == "rule"


def test_second_day2_load_reuses_persisted_exercises(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _create_five_day_plan(client)
    plan_id = data["plan"]["id"]
    day2 = _select_day(db_session, plan_id, 2)[1]
    original_generate = exercise_generator.generate_exercises
    calls = 0

    def counted_generate(*args: Any, **kwargs: Any):
        nonlocal calls
        calls += 1
        return original_generate(*args, **kwargs)

    monkeypatch.setattr(exercise_generator, "generate_exercises", counted_generate)
    first = client.get(f"/api/plans/{plan_id}/today")
    first_ids = [item["id"] for item in first.json()["task"]["exercises"]]
    second = client.get(f"/api/plans/{plan_id}/today")
    second_ids = [item["id"] for item in second.json()["task"]["exercises"]]

    assert first.status_code == second.status_code == 200
    assert calls == 1
    assert first_ids == second_ids
    assert db_session.scalar(select(func.count(Exercise.id)).where(Exercise.task_id == day2.id)) == 3
    assert db_session.scalar(
        select(func.count(AgentTrace.id)).where(
            AgentTrace.task_id == day2.id,
            AgentTrace.tool_name == "exercise_auto_generator",
        )
    ) == 1


def test_day5_auto_generation_uses_medium_difficulty(
    client: TestClient,
    db_session: Session,
) -> None:
    data = _create_five_day_plan(client)
    plan_id = data["plan"]["id"]
    day5 = _select_day(db_session, plan_id, 5)[4]

    response = client.get(f"/api/plans/{plan_id}/today")

    assert response.status_code == 200, response.text
    assert response.json()["task"]["id"] == day5.id
    assert {item["difficulty"] for item in response.json()["task"]["exercises"]} == {"medium"}


@pytest.mark.parametrize(
    ("llm_client", "expected_mode"),
    [
        (None, "rule"),
        (AutoExerciseLLM(), "llm"),
        (AutoExerciseLLM(fail=True), "fallback_rule"),
    ],
    ids=["rule", "llm", "fallback-rule"],
)
def test_daily_auto_generation_preserves_execution_modes(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    llm_client: LLMClient | None,
    expected_mode: str,
) -> None:
    data = _create_five_day_plan(client)
    plan_id = data["plan"]["id"]
    day2 = _select_day(db_session, plan_id, 2)[1]
    monkeypatch.setattr("app.api.plans.get_llm_client", lambda: llm_client)

    response = client.get(f"/api/plans/{plan_id}/today")

    assert response.status_code == 200, response.text
    assert len(response.json()["task"]["exercises"]) == 3
    trace = _auto_trace(db_session, day2.id)
    assert trace.execution_mode == expected_mode
    if expected_mode == "llm":
        assert trace.provider == "fake-auto-provider"
        assert trace.model_name == "fake-auto-model"
    if expected_mode == "fallback_rule":
        assert trace.fallback_reason == "LLMInvalidResponseError"
