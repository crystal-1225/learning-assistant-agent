from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import DailyTask, Exercise, TaskStatus
from app.tools.progress_evaluator import MasteryUpdate
from app.tools.weak_point_detector import detect_weak_points


def create_user(client: TestClient) -> int:
    response = client.post("/api/users", json={"name": "查询测试用户"})
    assert response.status_code == 200
    return response.json()["id"]


def create_plan(client: TestClient, *, start_date: str = "2026-07-11", end_date: str = "2026-07-13") -> dict:
    user_id = create_user(client)
    response = client.post(
        "/api/courses/from-text",
        json={
            "user_id": user_id,
            "course_title": "高等数学",
            "goal": "3天复习极限，准备小测",
            "start_date": start_date,
            "end_date": end_date,
            "daily_minutes": 40,
            "material_text": "极限定义：函数趋近。重要极限：sinx/x。无穷小比较；等价无穷小。洛必达法则：求未定式。",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def correct_answers(db_session: Session, task_id: int, *, correct_count: int | None = None) -> list[dict]:
    exercises = db_session.scalars(select(Exercise).where(Exercise.task_id == task_id).order_by(Exercise.id)).all()
    answers: list[dict] = []
    for index, exercise in enumerate(exercises):
        is_correct = correct_count is None or index < correct_count
        answers.append({"exercise_id": exercise.id, "user_answer": exercise.standard_answer if is_correct else "错误答案"})
    return answers


@pytest.mark.parametrize(
    ("rate", "expected_weak"),
    [
        (0.0, True),
        (0.59, True),
        (0.6, True),
        (0.79, True),
        (0.8, False),
        (1.0, False),
    ],
)
def test_weak_point_detector_boundaries(rate: float, expected_weak: bool) -> None:
    update = MasteryUpdate(
        knowledge_point_id=1,
        knowledge_point_title="极限定义",
        old_score=20,
        new_score=52,
        score_change=32,
        correct_count=int(rate * 100),
        total_count=100,
        confidence=0.5,
        change_reason="边界测试",
        current_correct_rate=rate,
    )
    assert bool(detect_weak_points([update])) is expected_weak


def test_get_plan_detail_sorted_and_no_answer_leak(client: TestClient) -> None:
    created = create_plan(client)
    response = client.get(f"/api/plans/{created['plan']['id']}")
    assert response.status_code == 200
    data = response.json()
    assert data["course"]["title"] == "高等数学"
    assert data["knowledge_points"]
    assert data["mastery_records"]
    dates = [task["task_date"] for task in data["plan"]["daily_tasks"]]
    assert dates == sorted(dates)
    text = str(data)
    assert "standard_answer" not in text
    assert "explanation" not in text
    assert "答案应包含" not in text


def test_get_missing_plan_returns_404(client: TestClient) -> None:
    assert client.get("/api/plans/999").status_code == 404
    assert client.get("/api/plans/999/today").status_code == 404
    assert client.get("/api/plans/999/trace").status_code == 404


def test_today_returns_earliest_incomplete_when_no_system_today_task(client: TestClient) -> None:
    created = create_plan(client, start_date="2026-07-01", end_date="2026-07-03")
    response = client.get(f"/api/plans/{created['plan']['id']}/today")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["task"]["task_date"] == "2026-07-01"


def test_today_returns_all_completed_when_done(client: TestClient, db_session: Session) -> None:
    created = create_plan(client, start_date="2026-07-01", end_date="2026-07-01")
    task_id = created["today_task"]["id"]
    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={"completed": True, "answers": correct_answers(db_session, task_id), "self_rating": 5},
    )
    assert response.status_code == 200
    today = client.get(f"/api/plans/{created['plan']['id']}/today").json()
    assert today["status"] == "all_completed"
    assert today["task"] is None


def test_trace_filters(client: TestClient, db_session: Session) -> None:
    created = create_plan(client)
    task_id = created["today_task"]["id"]
    submit = client.post(
        f"/api/tasks/{task_id}/submit",
        json={"completed": True, "answers": correct_answers(db_session, task_id, correct_count=1), "self_rating": 3},
    )
    assert submit.status_code == 200
    plan_id = created["plan"]["id"]
    all_trace = client.get(f"/api/plans/{plan_id}/trace")
    assert all_trace.status_code == 200
    filtered = client.get(f"/api/plans/{plan_id}/trace", params={"task_id": task_id, "tool_name": "answer_evaluator"})
    assert filtered.status_code == 200
    data = filtered.json()
    assert len(data) == 1
    assert data[0]["task_id"] == task_id
    assert data[0]["tool_name"] == "answer_evaluator"


def test_past_date_plan_replanner_uses_submitted_task_date(client: TestClient, db_session: Session) -> None:
    created = create_plan(client, start_date="2026-06-01", end_date="2026-06-03")
    task_id = created["today_task"]["id"]
    future_task_id = created["plan"]["daily_tasks"][1]["id"]
    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={"completed": True, "answers": correct_answers(db_session, task_id, correct_count=0), "self_rating": 1},
    )
    assert response.status_code == 200
    db_session.expire_all()
    future_task = db_session.get(DailyTask, future_task_id)
    current_task = db_session.get(DailyTask, task_id)
    assert future_task is not None
    assert current_task is not None
    assert future_task.status == TaskStatus.ADJUSTED.value
    assert current_task.content != future_task.content


def test_health_database_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
        "service": "zhixuehuan-agent-backend",
    }


def test_health_database_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import main

    class BrokenSession:
        def execute(self, *args, **kwargs):
            raise RuntimeError("database unavailable")

        def close(self) -> None:
            pass

    monkeypatch.setattr(main, "SessionLocal", lambda: BrokenSession())
    response = TestClient(main.app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert response.json()["database"] == "error"
