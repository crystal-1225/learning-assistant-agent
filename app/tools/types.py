from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class GoalSummary:
    goal: str
    start_date: date
    end_date: date
    daily_minutes: int
    total_days: int
    summary: str


@dataclass(frozen=True)
class KnowledgePointDraft:
    title: str
    description: str
    difficulty: str
    importance: int = 3
    source_hint: str = "规则提取"


@dataclass(frozen=True)
class DayPlanDraft:
    task_date: date
    title: str
    content: str
    knowledge_point_indexes: list[int]


@dataclass(frozen=True)
class ExerciseDraft:
    knowledge_point_index: int
    question: str
    standard_answer: str
    explanation: str
    difficulty: str
    question_type: str = "short_answer"
