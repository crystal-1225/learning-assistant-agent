import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    AgentTrace,
    DailyTask,
    Exercise,
    MasteryRecord,
    Submission,
    SubmissionAnswer,
    TaskStatus,
)
from app.tools import answer_evaluator, replanner
from app.tools.weak_point_detector import WeakKnowledgePoint


def create_plan(client: TestClient) -> dict:
    user_response = client.post("/api/users", json={"name": "提交测试用户"})
    assert user_response.status_code == 200
    user_id = user_response.json()["id"]
    response = client.post(
        "/api/courses/from-text",
        json={
            "user_id": user_id,
            "course_title": "高等数学",
            "goal": "3天复习极限，准备小测",
            "start_date": "2026-07-11",
            "end_date": "2026-07-13",
            "daily_minutes": 40,
            "material_text": "极限定义：函数趋近。重要极限：sinx/x。无穷小比较；等价无穷小。洛必达法则：求未定式。",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def answers_for_task(db_session: Session, task_id: int, *, correct_count: int | None = None) -> list[dict]:
    exercises = db_session.scalars(select(Exercise).where(Exercise.task_id == task_id).order_by(Exercise.id)).all()
    answers: list[dict] = []
    for index, exercise in enumerate(exercises):
        is_correct = correct_count is None or index < correct_count
        answers.append(
            {
                "exercise_id": exercise.id,
                "user_answer": exercise.standard_answer if is_correct else "错误答案",
            }
        )
    return answers


def submit_task(
    client: TestClient,
    task_id: int,
    answers: list[dict],
    *,
    completed: bool = True,
    self_rating: int = 3,
    notes: str | None = "重要极限仍然不熟",
) -> dict:
    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "completed": completed,
            "answers": answers,
            "self_rating": self_rating,
            "notes": notes,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_submit_all_correct_success(client: TestClient, db_session: Session) -> None:
    plan = create_plan(client)
    task_id = plan["today_task"]["id"]
    data = submit_task(client, task_id, answers_for_task(db_session, task_id, correct_count=None), self_rating=5)
    assert data["completed"] is True
    assert data["correct_rate"] == 1.0
    assert all(item["is_correct"] for item in data["answer_results"])


def test_submit_partially_wrong_success_and_correct_rate_is_server_calculated(
    client: TestClient,
    db_session: Session,
) -> None:
    plan = create_plan(client)
    task_id = plan["today_task"]["id"]
    data = submit_task(client, task_id, answers_for_task(db_session, task_id, correct_count=2))
    assert data["correct_rate"] == 0.67
    assert [item["is_correct"] for item in data["answer_results"]].count(True) == 2


def test_client_cannot_send_correct_rate(client: TestClient, db_session: Session) -> None:
    plan = create_plan(client)
    task_id = plan["today_task"]["id"]
    payload = {
        "completed": True,
        "answers": answers_for_task(db_session, task_id, correct_count=1),
        "self_rating": 3,
        "correct_rate": 1.0,
    }
    response = client.post(f"/api/tasks/{task_id}/submit", json=payload)
    assert response.status_code == 422


def test_numeric_answer_one_point_zero_equals_one(client: TestClient, db_session: Session) -> None:
    plan = create_plan(client)
    task_id = plan["today_task"]["id"]
    exercise = db_session.scalars(select(Exercise).where(Exercise.task_id == task_id).order_by(Exercise.id)).first()
    assert exercise is not None
    exercise.standard_answer = "1"
    db_session.commit()
    data = submit_task(client, task_id, [{"exercise_id": exercise.id, "user_answer": "1.0"}])
    assert data["correct_rate"] == 1.0
    assert data["answer_results"][0]["evaluation_reason"] == "数字标准化后答案一致"


def test_letter_answer_ignores_case(client: TestClient, db_session: Session) -> None:
    plan = create_plan(client)
    task_id = plan["today_task"]["id"]
    exercise = db_session.scalars(select(Exercise).where(Exercise.task_id == task_id).order_by(Exercise.id)).first()
    assert exercise is not None
    exercise.standard_answer = "A"
    db_session.commit()
    data = submit_task(client, task_id, [{"exercise_id": exercise.id, "user_answer": "a"}])
    assert data["correct_rate"] == 1.0
    assert data["answer_results"][0]["is_correct"] is True


def test_missing_task_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/tasks/999/submit",
        json={"completed": True, "answers": [{"exercise_id": 1, "user_answer": "1"}], "self_rating": 3},
    )
    assert response.status_code == 404


def test_missing_exercise_returns_400(client: TestClient) -> None:
    plan = create_plan(client)
    response = client.post(
        f"/api/tasks/{plan['today_task']['id']}/submit",
        json={"completed": True, "answers": [{"exercise_id": 999, "user_answer": "1"}], "self_rating": 3},
    )
    assert response.status_code == 400


def test_exercise_from_other_task_returns_400(client: TestClient, db_session: Session) -> None:
    plan = create_plan(client)
    today_task_id = plan["today_task"]["id"]
    later_task_id = plan["plan"]["daily_tasks"][1]["id"]
    exercise = db_session.scalars(select(Exercise).where(Exercise.task_id == today_task_id)).first()
    assert exercise is not None
    response = client.post(
        f"/api/tasks/{later_task_id}/submit",
        json={"completed": True, "answers": [{"exercise_id": exercise.id, "user_answer": "1"}], "self_rating": 3},
    )
    assert response.status_code == 400


def test_duplicate_exercise_id_returns_422(client: TestClient, db_session: Session) -> None:
    plan = create_plan(client)
    task_id = plan["today_task"]["id"]
    exercise = db_session.scalars(select(Exercise).where(Exercise.task_id == task_id)).first()
    assert exercise is not None
    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={
            "completed": True,
            "answers": [
                {"exercise_id": exercise.id, "user_answer": "1"},
                {"exercise_id": exercise.id, "user_answer": "1"},
            ],
            "self_rating": 3,
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize("self_rating", [0, 6])
def test_self_rating_out_of_range_returns_422(client: TestClient, db_session: Session, self_rating: int) -> None:
    plan = create_plan(client)
    task_id = plan["today_task"]["id"]
    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={"completed": True, "answers": answers_for_task(db_session, task_id, correct_count=1), "self_rating": self_rating},
    )
    assert response.status_code == 422


def test_empty_answers_returns_422(client: TestClient) -> None:
    plan = create_plan(client)
    response = client.post(
        f"/api/tasks/{plan['today_task']['id']}/submit",
        json={"completed": True, "answers": [], "self_rating": 3},
    )
    assert response.status_code == 422


def test_repeated_task_submission_returns_409(client: TestClient, db_session: Session) -> None:
    plan = create_plan(client)
    task_id = plan["today_task"]["id"]
    answers = answers_for_task(db_session, task_id, correct_count=1)
    submit_task(client, task_id, answers)
    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={"completed": True, "answers": answers, "self_rating": 3},
    )
    assert response.status_code == 409


def test_mastery_increases_after_all_correct(client: TestClient, db_session: Session) -> None:
    plan = create_plan(client)
    task_id = plan["today_task"]["id"]
    data = submit_task(client, task_id, answers_for_task(db_session, task_id, correct_count=None), self_rating=5)
    assert data["mastery_updates"]
    assert all(item["old_score"] == 20.0 for item in data["mastery_updates"])
    assert all(item["new_score"] > item["old_score"] for item in data["mastery_updates"])


def test_many_wrong_answers_detect_weak_points(client: TestClient, db_session: Session) -> None:
    plan = create_plan(client)
    task_id = plan["today_task"]["id"]
    data = submit_task(client, task_id, answers_for_task(db_session, task_id, correct_count=0), self_rating=1)
    assert data["weak_knowledge_points"]
    assert any("补救复习" in item["reason"] for item in data["weak_knowledge_points"])
    assert all(0 <= item["new_score"] <= 100 for item in data["mastery_updates"])
    assert all(item["new_score"] <= item["old_score"] for item in data["mastery_updates"])


def test_weak_points_are_added_to_future_task(client: TestClient, db_session: Session) -> None:
    plan = create_plan(client)
    task_id = plan["today_task"]["id"]
    future_task_id = plan["plan"]["daily_tasks"][1]["id"]
    before = db_session.get(DailyTask, future_task_id)
    assert before is not None
    original_content = before.content
    data = submit_task(client, task_id, answers_for_task(db_session, task_id, correct_count=0), self_rating=1)
    db_session.expire_all()
    future_task = db_session.get(DailyTask, future_task_id)
    assert future_task is not None
    assert data["weak_knowledge_points"]
    assert future_task.status == TaskStatus.ADJUSTED.value
    assert future_task.content != original_content
    assert "额外学习10分钟" in future_task.content
    assert data["adjusted_tasks"] == [
        {
            "id": future_task_id,
            "task_date": future_task.task_date.isoformat(),
            "title": future_task.title,
            "status": "adjusted",
            "adjustment_reason": future_task.adjustment_reason,
        }
    ]
    assert "薄弱知识点" in (future_task.adjustment_reason or "")
    assert "触发依据" in (future_task.adjustment_reason or "")
    assert "调整内容" in (future_task.adjustment_reason or "")


def test_replanner_does_not_insert_duplicate_remedial_content(client: TestClient, db_session: Session) -> None:
    plan = create_plan(client)
    task_id = plan["today_task"]["id"]
    future_task_id = plan["plan"]["daily_tasks"][1]["id"]
    data = submit_task(client, task_id, answers_for_task(db_session, task_id, correct_count=0), self_rating=1)
    db_session.expire_all()
    current_task = db_session.get(DailyTask, task_id)
    future_task = db_session.get(DailyTask, future_task_id)
    assert current_task is not None and future_task is not None
    original_content = future_task.content
    original_reason = future_task.adjustment_reason
    weak_points = [
        WeakKnowledgePoint(
            id=item["id"],
            title=item["title"],
            mastery_score=item["mastery_score"],
            current_correct_rate=item["current_correct_rate"],
            reason=item["reason"],
        )
        for item in data["weak_knowledge_points"]
    ]

    result = replanner.adjust_future_tasks(
        current_task=current_task,
        future_tasks=[future_task],
        weak_knowledge_points=weak_points,
        notes=None,
    )

    assert result.adjusted_task_ids == []
    assert future_task.content == original_content
    assert future_task.adjustment_reason == original_reason


def test_no_weak_points_keeps_future_task_unchanged(client: TestClient, db_session: Session) -> None:
    plan = create_plan(client)
    task_id = plan["today_task"]["id"]
    for record in db_session.scalars(select(MasteryRecord)).all():
        record.old_score = 90
        record.new_score = 90
        record.score = 90
        record.confidence = 0.5
    db_session.commit()
    future_task_id = plan["plan"]["daily_tasks"][1]["id"]
    before = db_session.get(DailyTask, future_task_id)
    assert before is not None
    original_content = before.content
    data = submit_task(client, task_id, answers_for_task(db_session, task_id, correct_count=None), self_rating=5)
    db_session.expire_all()
    future_task = db_session.get(DailyTask, future_task_id)
    assert future_task is not None
    assert data["weak_knowledge_points"] == []
    assert future_task.content == original_content


def test_all_correct_from_initial_score_does_not_trigger_replanner(client: TestClient, db_session: Session) -> None:
    plan = create_plan(client)
    task_id = plan["today_task"]["id"]
    future_task_id = plan["plan"]["daily_tasks"][1]["id"]
    before = db_session.get(DailyTask, future_task_id)
    assert before is not None
    original_content = before.content
    data = submit_task(client, task_id, answers_for_task(db_session, task_id, correct_count=None), self_rating=5)
    db_session.expire_all()
    future_task = db_session.get(DailyTask, future_task_id)
    assert future_task is not None
    assert data["correct_rate"] == 1.0
    assert data["weak_knowledge_points"] == []
    assert data["adjustment_summary"] == "未发现明显薄弱知识点，后续计划保持不变"
    assert future_task.content == original_content


def test_completed_current_task_is_not_modified_by_replanner(client: TestClient, db_session: Session) -> None:
    plan = create_plan(client)
    task_id = plan["today_task"]["id"]
    task = db_session.get(DailyTask, task_id)
    assert task is not None
    original_content = task.content
    submit_task(client, task_id, answers_for_task(db_session, task_id, correct_count=0), self_rating=1)
    db_session.expire_all()
    current_task = db_session.get(DailyTask, task_id)
    assert current_task is not None
    assert current_task.status == TaskStatus.COMPLETED.value
    assert current_task.content == original_content


def test_completed_future_task_is_not_adjusted(client: TestClient, db_session: Session) -> None:
    plan = create_plan(client)
    task_id = plan["today_task"]["id"]
    completed_future_id = plan["plan"]["daily_tasks"][1]["id"]
    remaining_future_id = plan["plan"]["daily_tasks"][2]["id"]
    completed_future = db_session.get(DailyTask, completed_future_id)
    assert completed_future is not None
    original_content = completed_future.content
    completed_future.status = TaskStatus.COMPLETED.value
    db_session.commit()

    data = submit_task(client, task_id, answers_for_task(db_session, task_id, correct_count=0), self_rating=1)
    db_session.expire_all()
    completed_future = db_session.get(DailyTask, completed_future_id)
    assert completed_future is not None
    assert completed_future.status == TaskStatus.COMPLETED.value
    assert completed_future.content == original_content
    assert data["adjusted_tasks"][0]["id"] == remaining_future_id


def test_submission_response_does_not_return_standard_answer(client: TestClient, db_session: Session) -> None:
    plan = create_plan(client)
    task_id = plan["today_task"]["id"]
    data = submit_task(client, task_id, answers_for_task(db_session, task_id, correct_count=1))
    response_text = str(data)
    assert "standard_answer" not in response_text
    assert "答案应包含" not in response_text


def test_submission_failure_rolls_back(client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = create_plan(client)
    task_id = plan["today_task"]["id"]

    def broken_evaluator(*args, **kwargs):
        raise RuntimeError("forced evaluation failure")

    monkeypatch.setattr(answer_evaluator, "evaluate_answer", broken_evaluator)
    response = client.post(
        f"/api/tasks/{task_id}/submit",
        json={"completed": True, "answers": answers_for_task(db_session, task_id, correct_count=1), "self_rating": 3},
    )
    assert response.status_code == 500
    assert db_session.scalars(select(Submission)).all() == []
    assert db_session.scalars(select(SubmissionAnswer)).all() == []


def test_submission_agent_trace_is_readable(client: TestClient, db_session: Session) -> None:
    plan = create_plan(client)
    task_id = plan["today_task"]["id"]
    data = submit_task(client, task_id, answers_for_task(db_session, task_id, correct_count=1))
    tool_names = {trace["tool_name"] for trace in data["trace"]}
    assert tool_names >= {
        "validate_submission",
        "answer_evaluator",
        "progress_evaluator",
        "weak_point_detector",
        "replanner",
        "save_submission",
    }
    stored = db_session.scalars(select(AgentTrace).where(AgentTrace.task_id == task_id)).all()
    assert len(stored) >= 6
