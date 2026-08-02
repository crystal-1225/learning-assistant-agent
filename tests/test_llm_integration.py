from datetime import date
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.orchestrator import AgentOrchestrator
from app.llm.base import LLMCallMetadata, LLMClient
from app.llm.exceptions import LLMInvalidResponseError, LLMRequestError
from app.llm.schemas import LLMContentAnalysis, LLMExerciseSet, LLMGoalAnalysis
from app.models.entities import AgentTrace, Exercise, KnowledgePoint, User
from app.tools.exercise_generator import normalize_question


class FakeLLMClient(LLMClient):
    provider = "fake"
    model_name = "fake-model"

    def __init__(self, responses: dict[type[BaseModel], BaseModel | Exception]) -> None:
        self.responses = responses
        self.last_call_metadata = None

    def generate_structured(self, *, prompt: str, response_model: type[BaseModel], timeout_seconds: float | None = None) -> BaseModel:
        self.last_call_metadata = LLMCallMetadata(
            request_id=f"fake-{response_model.__name__}",
            retry_count=0,
            input_char_count=len(prompt),
            output_char_count=128,
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
        )
        response = self.responses.get(response_model)
        if isinstance(response, Exception):
            raise response
        if response is None:
            raise LLMRequestError("missing fake response")
        return response


def create_user(db_session: Session) -> User:
    user = User(name="LLM测试用户")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def create_with_llm(db_session: Session, llm_client: LLMClient | None) -> int:
    user = create_user(db_session)
    result = AgentOrchestrator(db_session, llm_client=llm_client).create_course_plan_from_text(
        user=user,
        course_title="高等数学",
        goal="3天复习极限",
        start_date=date(2026, 7, 11),
        end_date=date(2026, 7, 13),
        daily_minutes=40,
        material_text="极限定义。重要极限。无穷小比较。等价无穷小。",
    )
    return result.plan.id


def valid_goal() -> LLMGoalAnalysis:
    return LLMGoalAnalysis(
        objective="复习极限",
        target_topics=["极限定义"],
        constraints=["3天"],
        study_style="先概念后练习",
        summary="使用模型整理的学习目标摘要",
    )


def valid_content(points: list[dict[str, Any]] | None = None) -> LLMContentAnalysis:
    return LLMContentAnalysis(
        course_summary="模型课程摘要",
        knowledge_points=points
        or [
            {
                "title": "极限定义",
                "description": "理解函数趋近过程",
                "difficulty": "basic",
                "importance": 5,
                "source_hint": "资料开头",
            },
            {
                "title": "重要极限",
                "description": "掌握常见重要极限",
                "difficulty": "medium",
                "importance": 4,
                "source_hint": "资料中段",
            },
        ],
    )


def valid_exercises(title: str = "极限定义", secondary_title: str | None = None) -> LLMExerciseSet:
    secondary = secondary_title or ("重要极限" if title == "极限定义" else title)
    return LLMExerciseSet(
        exercises=[
            {
                "question": f"{title}的核心含义是什么？",
                "standard_answer": "描述函数趋近某个值的过程",
                "explanation": "检查概念理解",
                "difficulty": "basic",
                "knowledge_point_title": title,
                "question_type": "short_answer",
            },
            {
                "question": f"关于{secondary}，以下哪项更符合定义？\nA. 只背名称\nB. 结合条件理解\nC. 忽略条件\nD. 只看结论",
                "standard_answer": "B",
                "explanation": "检查单选判断",
                "difficulty": "basic",
                "knowledge_point_title": secondary,
                "question_type": "single_choice",
            },
            {
                "question": f"判断题：学习{title}时应关注适用条件。\nA. 正确\nB. 错误",
                "standard_answer": "A",
                "explanation": "检查基础判断",
                "difficulty": "basic",
                "knowledge_point_title": title,
                "question_type": "single_choice",
            },
        ]
    )


def test_llm_goal_content_and_exercise_success(db_session: Session) -> None:
    llm = FakeLLMClient(
        {
            LLMGoalAnalysis: valid_goal(),
            LLMContentAnalysis: valid_content(),
            LLMExerciseSet: valid_exercises("极限定义"),
        }
    )
    plan_id = create_with_llm(db_session, llm)
    traces = db_session.scalars(select(AgentTrace).where(AgentTrace.plan_id == plan_id)).all()
    modes = {trace.tool_name: trace.execution_mode for trace in traces}
    assert modes["goal_analyzer"] == "llm"
    assert modes["content_parser"] == "llm"
    assert modes["exercise_generator"] == "llm"
    llm_traces = [trace for trace in traces if trace.execution_mode == "llm"]
    assert all(trace.request_id for trace in llm_traces)
    assert all(trace.input_char_count and trace.input_char_count > 0 for trace in llm_traces)
    assert all(trace.total_tokens == 30 for trace in llm_traces)
    assert db_session.scalars(select(Exercise)).all()[0].question_type == "short_answer"


@pytest.mark.parametrize(
    "exception",
    [LLMRequestError("timeout"), LLMInvalidResponseError("invalid json")],
)
def test_llm_failure_falls_back_to_rule(db_session: Session, exception: Exception) -> None:
    llm = FakeLLMClient(
        {
            LLMGoalAnalysis: exception,
            LLMContentAnalysis: valid_content(),
            LLMExerciseSet: valid_exercises("极限定义"),
        }
    )
    plan_id = create_with_llm(db_session, llm)
    goal_trace = db_session.scalars(
        select(AgentTrace).where(AgentTrace.plan_id == plan_id, AgentTrace.tool_name == "goal_analyzer")
    ).one()
    assert goal_trace.execution_mode == "fallback_rule"
    assert goal_trace.fallback_reason in {"LLMRequestError", "LLMInvalidResponseError"}


def test_empty_knowledge_points_fallback(db_session: Session) -> None:
    llm = FakeLLMClient(
        {
            LLMGoalAnalysis: valid_goal(),
            LLMContentAnalysis: LLMInvalidResponseError("empty points"),
            LLMExerciseSet: valid_exercises("极限定义"),
        }
    )
    plan_id = create_with_llm(db_session, llm)
    trace = db_session.scalars(
        select(AgentTrace).where(AgentTrace.plan_id == plan_id, AgentTrace.tool_name == "content_parser")
    ).one()
    assert trace.execution_mode == "fallback_rule"


def test_llm_duplicate_points_are_sanitized_without_losing_valid_titles(db_session: Session) -> None:
    points = [
        {"title": "主题甲", "description": "甲", "difficulty": "basic", "importance": 1, "source_hint": "s"},
        {"title": "主题甲", "description": "甲重复", "difficulty": "basic", "importance": 1, "source_hint": "s"},
        {"title": "主题乙", "description": "乙", "difficulty": "basic", "importance": 1, "source_hint": "s"},
        {"title": "主题丙", "description": "丙", "difficulty": "basic", "importance": 1, "source_hint": "s"},
        {"title": "主题丁", "description": "丁", "difficulty": "basic", "importance": 1, "source_hint": "s"},
        {"title": "主题戊", "description": "戊", "difficulty": "basic", "importance": 1, "source_hint": "s"},
        {"title": "主题己", "description": "己", "difficulty": "basic", "importance": 1, "source_hint": "s"},
    ]
    llm = FakeLLMClient(
        {
            LLMGoalAnalysis: valid_goal(),
            LLMContentAnalysis: valid_content(points),
            LLMExerciseSet: valid_exercises("主题甲"),
        }
    )
    create_with_llm(db_session, llm)
    stored_titles = [point.title for point in db_session.scalars(select(KnowledgePoint).order_by(KnowledgePoint.id)).all()]
    assert stored_titles == ["主题甲", "主题乙", "主题丙", "主题丁", "主题戊", "主题己"]
    point_titles = [trace.output_summary for trace in db_session.scalars(select(AgentTrace)).all() if trace.tool_name == "content_parser"]
    assert point_titles == ["提取 6 个知识点。"]


def test_unmapped_llm_exercise_falls_back(db_session: Session) -> None:
    llm = FakeLLMClient(
        {
            LLMGoalAnalysis: valid_goal(),
            LLMContentAnalysis: valid_content(),
            LLMExerciseSet: valid_exercises("不存在的知识点"),
        }
    )
    plan_id = create_with_llm(db_session, llm)
    trace = db_session.scalars(
        select(AgentTrace).where(AgentTrace.plan_id == plan_id, AgentTrace.tool_name == "exercise_generator")
    ).one()
    assert trace.execution_mode == "fallback_rule"
    assert trace.fallback_reason == "ValueError"


def test_duplicate_llm_exercises_fall_back_to_distinct_rule_exercises(db_session: Session) -> None:
    title = "极限定义"
    duplicate_exercises = LLMExerciseSet(
        exercises=[
            {
                "question": f"请解释{title}？",
                "standard_answer": "说明极限的含义",
                "explanation": "概念题",
                "difficulty": "basic",
                "knowledge_point_title": title,
                "question_type": "short_answer",
            },
            {
                "question": f" 请 解释 {title} 。 ",
                "standard_answer": "说明极限的含义",
                "explanation": "概念题",
                "difficulty": "basic",
                "knowledge_point_title": title,
                "question_type": "short_answer",
            },
            {
                "question": f"请解释{title}！",
                "standard_answer": "说明极限的含义",
                "explanation": "概念题",
                "difficulty": "basic",
                "knowledge_point_title": title,
                "question_type": "short_answer",
            },
        ]
    )
    llm = FakeLLMClient(
        {
            LLMGoalAnalysis: valid_goal(),
            LLMContentAnalysis: valid_content(),
            LLMExerciseSet: duplicate_exercises,
        }
    )

    plan_id = create_with_llm(db_session, llm)
    trace = db_session.scalars(
        select(AgentTrace).where(AgentTrace.plan_id == plan_id, AgentTrace.tool_name == "exercise_generator")
    ).one()
    questions = [exercise.question for exercise in db_session.scalars(select(Exercise).order_by(Exercise.id)).all()]

    assert trace.execution_mode == "fallback_rule"
    assert trace.fallback_reason == "ValueError"
    assert len(questions) == 3
    assert len({normalize_question(question) for question in questions}) == 3


def test_llm_wrong_exercise_difficulty_falls_back_to_rule(db_session: Session) -> None:
    wrong_difficulty = valid_exercises("极限定义")
    wrong_difficulty.exercises[2].difficulty = "medium"
    llm = FakeLLMClient(
        {
            LLMGoalAnalysis: valid_goal(),
            LLMContentAnalysis: valid_content(),
            LLMExerciseSet: wrong_difficulty,
        }
    )

    plan_id = create_with_llm(db_session, llm)
    trace = db_session.scalars(
        select(AgentTrace).where(AgentTrace.plan_id == plan_id, AgentTrace.tool_name == "exercise_generator")
    ).one()
    exercises = db_session.scalars(select(Exercise).order_by(Exercise.id)).all()

    assert trace.execution_mode == "fallback_rule"
    assert trace.fallback_reason == "ValueError"
    assert {exercise.difficulty for exercise in exercises} == {"basic"}


def test_no_api_key_rule_mode_still_runs_and_no_answer_leak(client) -> None:
    user = client.post("/api/users", json={"name": "无key用户"}).json()
    response = client.post(
        "/api/courses/from-text",
        json={
            "user_id": user["id"],
            "course_title": "高等数学",
            "goal": "3天复习极限",
            "start_date": "2026-07-11",
            "end_date": "2026-07-13",
            "daily_minutes": 40,
            "material_text": "极限定义。重要极限。无穷小比较。",
        },
    )
    assert response.status_code == 200
    text = response.text
    assert "standard_answer" not in text
    trace = response.json()["trace"]
    assert {item["execution_mode"] for item in trace} == {"rule"}


def test_api_key_not_in_trace_or_response(db_session: Session) -> None:
    api_key = "sk-secret-should-not-appear"
    llm = FakeLLMClient(
        {
            LLMGoalAnalysis: valid_goal(),
            LLMContentAnalysis: valid_content(),
            LLMExerciseSet: valid_exercises("极限定义"),
        }
    )
    llm.provider = "fake-provider"
    llm.model_name = "fake-model"
    plan_id = create_with_llm(db_session, llm)
    traces = db_session.scalars(select(AgentTrace).where(AgentTrace.plan_id == plan_id)).all()
    trace_text = " ".join(f"{trace.input_summary} {trace.output_summary} {trace.provider} {trace.model_name}" for trace in traces)
    assert api_key not in trace_text
