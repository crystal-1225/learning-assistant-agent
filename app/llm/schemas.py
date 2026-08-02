from typing import Literal

from pydantic import BaseModel, Field, field_validator


Difficulty = Literal["basic", "medium", "hard"]
QuestionType = Literal["single_choice", "short_answer"]


class LLMGoalAnalysis(BaseModel):
    objective: str = Field(min_length=1, max_length=500)
    target_topics: list[str] = Field(default_factory=list, max_length=8)
    constraints: list[str] = Field(default_factory=list, max_length=8)
    study_style: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=800)

    @field_validator("target_topics", "constraints")
    @classmethod
    def strip_list_items(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value.strip()]


class LLMKnowledgePoint(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=300)
    difficulty: Difficulty = "basic"
    importance: int = Field(ge=1, le=5)
    source_hint: str = Field(min_length=1, max_length=160)

    @field_validator("title", "description", "source_hint")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class LLMContentAnalysis(BaseModel):
    course_summary: str = Field(min_length=1, max_length=800)
    knowledge_points: list[LLMKnowledgePoint] = Field(min_length=1, max_length=8)


class LLMExercise(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    standard_answer: str = Field(min_length=1, max_length=1000)
    explanation: str = Field(min_length=1, max_length=1000)
    difficulty: Difficulty = "basic"
    knowledge_point_title: str = Field(min_length=1, max_length=80)
    question_type: QuestionType


class LLMExerciseSet(BaseModel):
    exercises: list[LLMExercise] = Field(min_length=3, max_length=3)

