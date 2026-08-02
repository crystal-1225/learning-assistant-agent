from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name cannot be blank")
        return stripped


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime


class CourseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    title: str
    description: str | None = None
    created_at: datetime


class CourseFromTextCreate(BaseModel):
    user_id: int
    course_title: str = Field(min_length=1, max_length=120)
    goal: str = Field(min_length=1, max_length=2000)
    start_date: date
    end_date: date
    daily_minutes: int = Field(gt=0, le=600)
    material_text: str = Field(min_length=1, max_length=50000)

    @field_validator("course_title", "goal", "material_text")
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field cannot be blank")
        return stripped

    @model_validator(mode="after")
    def validate_date_range(self) -> "CourseFromTextCreate":
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be earlier than start_date")
        days = (self.end_date - self.start_date).days + 1
        if days > 30:
            raise ValueError("date range cannot exceed 30 days")
        return self


class KnowledgePointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    title: str
    description: str | None = None
    difficulty: str


class ExerciseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    knowledge_point_id: int
    question: str
    difficulty: str
    question_type: str


class DailyTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    plan_id: int
    task_date: date
    title: str
    content: str
    status: str
    adjustment_reason: str | None = None
    knowledge_points: list[KnowledgePointRead] = Field(default_factory=list)
    exercises: list[ExerciseRead] = Field(default_factory=list)


class StudyPlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    goal: str
    start_date: date
    end_date: date
    daily_minutes: int
    status: str
    daily_tasks: list[DailyTaskRead] = Field(default_factory=list)


class AgentTraceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    plan_id: int | None = None
    task_id: int | None = None
    step: str
    tool_name: str
    reason_summary: str
    input_summary: str
    output_summary: str
    status: str
    duration_ms: int
    execution_mode: str
    provider: str | None = None
    model_name: str | None = None
    fallback_reason: str | None = None
    request_id: str | None = None
    retry_count: int = 0
    input_char_count: int | None = None
    output_char_count: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    created_at: datetime


class CourseCreationResponse(BaseModel):
    course: CourseRead
    plan: StudyPlanRead
    knowledge_points: list[KnowledgePointRead]
    today_task: DailyTaskRead
    trace: list[AgentTraceRead]


class MasteryRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    knowledge_point_id: int
    submission_id: int | None = None
    old_score: float
    new_score: float
    score: float
    confidence: float
    change_reason: str
    created_at: datetime
    updated_at: datetime


class StudyPlanDetailRead(BaseModel):
    plan: StudyPlanRead
    course: CourseRead
    knowledge_points: list[KnowledgePointRead]
    mastery_records: list[MasteryRecordRead]


class TodayTaskResponse(BaseModel):
    status: str
    task: DailyTaskRead | None = None
    message: str | None = None


class SubmissionAnswerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise_id: int
    user_answer: str = Field(min_length=1, max_length=5000)

    @field_validator("user_answer")
    @classmethod
    def answer_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("user_answer cannot be blank")
        return stripped


class TaskSubmissionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completed: StrictBool
    answers: list[SubmissionAnswerCreate] = Field(min_length=1)
    self_rating: int = Field(ge=1, le=5)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def exercise_ids_must_be_unique(self) -> "TaskSubmissionCreate":
        exercise_ids = [answer.exercise_id for answer in self.answers]
        if len(exercise_ids) != len(set(exercise_ids)):
            raise ValueError("exercise_id cannot be submitted more than once")
        if self.notes is not None:
            self.notes = self.notes.strip() or None
        return self


class SubmissionAnswerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    exercise_id: int
    is_correct: bool
    evaluation_reason: str


class MasteryUpdateRead(BaseModel):
    knowledge_point_id: int
    knowledge_point_title: str
    old_score: float
    new_score: float
    score_change: float
    correct_count: int
    total_count: int
    change_reason: str


class WeakKnowledgePointRead(BaseModel):
    id: int
    title: str
    mastery_score: float
    current_correct_rate: float
    reason: str


class AdjustedTaskRead(BaseModel):
    id: int
    task_date: date
    title: str
    status: str
    adjustment_reason: str | None = None


class TaskSubmissionResponse(BaseModel):
    submission_id: int
    task_id: int
    completed: bool
    correct_rate: float
    answer_results: list[SubmissionAnswerRead]
    mastery_updates: list[MasteryUpdateRead]
    weak_knowledge_points: list[WeakKnowledgePointRead]
    adjustment_summary: str
    adjusted_tasks: list[AdjustedTaskRead] = Field(default_factory=list)
    trace: list[AgentTraceRead]
