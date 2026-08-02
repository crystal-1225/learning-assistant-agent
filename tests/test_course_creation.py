from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.orchestrator import AgentOrchestrator
from app.models.entities import AgentTrace, Course, DailyTask, Exercise, KnowledgePoint, User
from app.tools import exercise_generator
from app.tools.exercise_generator import normalize_question


def create_demo_user(client: TestClient, name: str = "演示用户") -> dict:
    response = client.post("/api/users", json={"name": name})
    assert response.status_code == 200
    return response.json()


def valid_course_payload(user_id: int) -> dict:
    return {
        "user_id": user_id,
        "course_title": "高等数学",
        "goal": "3天复习极限，准备小测",
        "start_date": "2026-07-11",
        "end_date": "2026-07-13",
        "daily_minutes": 40,
        "material_text": "极限的定义：函数趋近。重要极限：sinx/x。无穷小比较；等价无穷小。洛必达法则：求未定式。",
    }


def create_course_plan(client: TestClient) -> dict:
    user = create_demo_user(client)
    response = client.post("/api/courses/from-text", json=valid_course_payload(user["id"]))
    assert response.status_code == 200, response.text
    return response.json()


def test_create_user_success(client: TestClient) -> None:
    data = create_demo_user(client)
    assert data["id"] == 1
    assert data["name"] == "演示用户"
    assert "created_at" in data


@pytest.mark.parametrize("name", ["", "   "])
def test_create_user_blank_name_fails(client: TestClient, name: str) -> None:
    response = client.post("/api/users", json={"name": name})
    assert response.status_code == 422


def test_create_course_from_text_success(client: TestClient) -> None:
    data = create_course_plan(client)
    assert data["course"]["title"] == "高等数学"
    assert data["plan"]["goal"] == "3天复习极限，准备小测"
    assert data["today_task"]["id"] == data["plan"]["daily_tasks"][0]["id"]


def test_generates_one_to_five_knowledge_points(client: TestClient) -> None:
    data = create_course_plan(client)
    assert 1 <= len(data["knowledge_points"]) <= 12


def test_data_structure_course_uses_clean_knowledge_points_and_exercises(client: TestClient) -> None:
    user = create_demo_user(client)
    payload = valid_course_payload(user["id"])
    payload.update(
        {
            "course_title": "数据结构（C语言版）",
            "goal": "14天内掌握顺序表、单链表、栈、队列和C语言实现",
            "start_date": "2026-08-01",
            "end_date": "2026-08-14",
            "material_text": (
                "课程内容包括数据结构基本概念、时间复杂度、顺序表、单链表、栈、队列及基础应用。"
                "学习重点为理解逻辑结构与存储结构的关系，掌握插入、删除、查找等基本操作，"
                "并能够使用C语言完成核心代码实现。"
            ),
        }
    )
    response = client.post("/api/courses/from-text", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    titles = [point["title"] for point in data["knowledge_points"]]
    assert titles[:6] == ["数据结构基本概念", "时间复杂度", "顺序表", "单链表", "栈", "队列"]
    assert all("课程内容包括" not in title and "学习重点为" not in title for title in titles)
    assert all("课程内容包括" not in item["question"] for item in data["today_task"]["exercises"])
    questions = [item["question"] for item in data["today_task"]["exercises"]]
    assert "```c" in questions[2]
    assert [item["question_type"] for item in data["today_task"]["exercises"]] == [
        "short_answer",
        "single_choice",
        "short_answer",
    ]


def test_every_day_in_date_range_has_task(client: TestClient) -> None:
    data = create_course_plan(client)
    task_dates = [task["task_date"] for task in data["plan"]["daily_tasks"]]
    assert task_dates == ["2026-07-11", "2026-07-12", "2026-07-13"]


def test_first_day_has_exactly_three_exercises(client: TestClient) -> None:
    data = create_course_plan(client)
    assert len(data["today_task"]["exercises"]) == 3


def test_first_day_exercise_questions_are_unique(client: TestClient) -> None:
    data = create_course_plan(client)
    questions = [exercise["question"] for exercise in data["today_task"]["exercises"]]
    assert len({normalize_question(question) for question in questions}) == 3


def test_response_does_not_leak_answers(client: TestClient) -> None:
    data = create_course_plan(client)
    for exercise in data["today_task"]["exercises"]:
        assert "standard_answer" not in exercise
        assert "explanation" not in exercise
    response_text = str(data)
    assert "答案应包含" not in response_text
    assert "本题用于检查" not in response_text


def test_invalid_user_id_returns_404(client: TestClient) -> None:
    response = client.post("/api/courses/from-text", json=valid_course_payload(999))
    assert response.status_code == 404


def test_end_date_before_start_date_returns_422(client: TestClient) -> None:
    user = create_demo_user(client)
    payload = valid_course_payload(user["id"])
    payload["start_date"] = "2026-07-13"
    payload["end_date"] = "2026-07-11"
    response = client.post("/api/courses/from-text", json=payload)
    assert response.status_code == 422


@pytest.mark.parametrize("minutes", [0, -1])
def test_daily_minutes_must_be_positive(client: TestClient, minutes: int) -> None:
    user = create_demo_user(client)
    payload = valid_course_payload(user["id"])
    payload["daily_minutes"] = minutes
    response = client.post("/api/courses/from-text", json=payload)
    assert response.status_code == 422


@pytest.mark.parametrize("material_text", ["", "   "])
def test_material_text_must_not_be_blank(client: TestClient, material_text: str) -> None:
    user = create_demo_user(client)
    payload = valid_course_payload(user["id"])
    payload["material_text"] = material_text
    response = client.post("/api/courses/from-text", json=payload)
    assert response.status_code == 422


def test_agent_trace_is_readable(client: TestClient, db_session: Session) -> None:
    data = create_course_plan(client)
    traces = data["trace"]
    assert len(traces) >= 5
    assert {trace["tool_name"] for trace in traces} >= {
        "goal_analyzer",
        "content_parser",
        "plan_generator",
        "task_generator",
        "exercise_generator",
    }
    stored = db_session.scalars(select(AgentTrace).where(AgentTrace.plan_id == data["plan"]["id"])).all()
    assert len(stored) == len(traces)


def test_transaction_failure_leaves_no_partial_course(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    user = User(name="事务测试用户")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    def broken_generate_exercises(*args, **kwargs):
        raise RuntimeError("forced exercise generation failure")

    monkeypatch.setattr(exercise_generator, "generate_exercises", broken_generate_exercises)
    orchestrator = AgentOrchestrator(db_session)

    with pytest.raises(RuntimeError):
        orchestrator.create_course_plan_from_text(
            user=user,
            course_title="高等数学",
            goal="3天复习极限",
            start_date=date(2026, 7, 11),
            end_date=date(2026, 7, 13),
            daily_minutes=40,
            material_text="极限的定义。重要极限。无穷小比较。",
        )

    assert db_session.scalar(select(Course).where(Course.user_id == user.id)) is None
    assert db_session.scalars(select(KnowledgePoint)).all() == []
    assert db_session.scalars(select(DailyTask)).all() == []
    assert db_session.scalars(select(Exercise)).all() == []
