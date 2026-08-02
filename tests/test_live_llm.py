from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.orchestrator import AgentOrchestrator
from app.core.config import get_settings
from app.llm.client import get_llm_client
from app.models.entities import Exercise, User


@pytest.mark.live_llm
def test_live_llm_course_creation_minimal(db_session: Session) -> None:
    settings = get_settings()
    if not settings.llm_enabled or not settings.has_llm_api_key:
        pytest.skip("live LLM config is not available")
    llm_client = get_llm_client()
    if llm_client is None:
        pytest.skip("live LLM client is not available")

    user = User(name="真实模型联调用户")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    result = AgentOrchestrator(db_session, llm_client=llm_client).create_course_plan_from_text(
        user=user,
        course_title="C++数组",
        goal="2天掌握C++一维数组基础",
        start_date=date(2026, 7, 11),
        end_date=date(2026, 7, 12),
        daily_minutes=30,
        material_text="C++数组是一组相同类型元素的连续存储结构。下标从0开始。访问越界会导致未定义行为。常见操作包括遍历、求和、查找最大值。",
    )

    modes = {trace.tool_name: trace.execution_mode for trace in result.trace}
    assert modes["goal_analyzer"] == "llm"
    assert modes["content_parser"] == "llm"
    assert modes["exercise_generator"] == "llm"
    assert 1 <= len(result.knowledge_points) <= 12
    assert len(result.today_task.exercises) == 3
    assert db_session.scalars(select(Exercise)).all()
