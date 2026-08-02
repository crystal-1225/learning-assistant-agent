from datetime import date, datetime
from enum import Enum
from typing import Optional

from sqlalchemy import CheckConstraint, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class PlanStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class TaskStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    ADJUSTED = "adjusted"


class TraceStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    courses: Mapped[list["Course"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    mastery_records: Mapped[list["MasteryRecord"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user: Mapped["User"] = relationship(back_populates="courses")
    materials: Mapped[list["Material"]] = relationship(back_populates="course", cascade="all, delete-orphan")
    knowledge_points: Mapped[list["KnowledgePoint"]] = relationship(back_populates="course", cascade="all, delete-orphan")
    plans: Mapped[list["StudyPlan"]] = relationship(back_populates="course", cascade="all, delete-orphan")


class Material(Base):
    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    filename: Mapped[Optional[str]] = mapped_column(String(255))
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    course: Mapped["Course"] = relationship(back_populates="materials")


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    difficulty: Mapped[str] = mapped_column(String(32), default="basic", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    course: Mapped["Course"] = relationship(back_populates="knowledge_points")
    task_links: Mapped[list["DailyTaskKnowledgePoint"]] = relationship(
        back_populates="knowledge_point",
        cascade="all, delete-orphan",
    )
    exercises: Mapped[list["Exercise"]] = relationship(back_populates="knowledge_point")
    mastery_records: Mapped[list["MasteryRecord"]] = relationship(
        back_populates="knowledge_point",
        cascade="all, delete-orphan",
    )


class StudyPlan(Base):
    __tablename__ = "study_plans"
    __table_args__ = (
        CheckConstraint("daily_minutes > 0", name="ck_study_plans_daily_minutes_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    daily_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[PlanStatus] = mapped_column(String(32), default=PlanStatus.ACTIVE.value, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    course: Mapped["Course"] = relationship(back_populates="plans")
    daily_tasks: Mapped[list["DailyTask"]] = relationship(back_populates="plan", cascade="all, delete-orphan")
    traces: Mapped[list["AgentTrace"]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class DailyTask(Base):
    __tablename__ = "daily_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("study_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    task_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[TaskStatus] = mapped_column(String(32), default=TaskStatus.PENDING.value, nullable=False)
    adjustment_reason: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    plan: Mapped["StudyPlan"] = relationship(back_populates="daily_tasks")
    knowledge_point_links: Mapped[list["DailyTaskKnowledgePoint"]] = relationship(
        back_populates="daily_task",
        cascade="all, delete-orphan",
    )
    exercises: Mapped[list["Exercise"]] = relationship(back_populates="daily_task", cascade="all, delete-orphan")
    submissions: Mapped[list["Submission"]] = relationship(back_populates="daily_task", cascade="all, delete-orphan")
    traces: Mapped[list["AgentTrace"]] = relationship(back_populates="task")

    @property
    def knowledge_points(self) -> list["KnowledgePoint"]:
        return [link.knowledge_point for link in self.knowledge_point_links]


class DailyTaskKnowledgePoint(Base):
    __tablename__ = "daily_task_knowledge_points"
    __table_args__ = (
        UniqueConstraint("daily_task_id", "knowledge_point_id", name="uq_daily_task_knowledge_point"),
    )

    daily_task_id: Mapped[int] = mapped_column(
        ForeignKey("daily_tasks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    knowledge_point_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        primary_key=True,
    )

    daily_task: Mapped["DailyTask"] = relationship(back_populates="knowledge_point_links")
    knowledge_point: Mapped["KnowledgePoint"] = relationship(back_populates="task_links")


class Exercise(Base):
    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("daily_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    knowledge_point_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    standard_answer: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[str] = mapped_column(String(32), default="basic", nullable=False)
    question_type: Mapped[str] = mapped_column(String(32), default="short_answer", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    daily_task: Mapped["DailyTask"] = relationship(back_populates="exercises")
    knowledge_point: Mapped["KnowledgePoint"] = relationship(back_populates="exercises")
    submission_answers: Mapped[list["SubmissionAnswer"]] = relationship(back_populates="exercise")


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        CheckConstraint("self_rating >= 1 AND self_rating <= 5", name="ck_submissions_self_rating_range"),
        CheckConstraint("correct_rate >= 0 AND correct_rate <= 1", name="ck_submissions_correct_rate_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("daily_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    completed: Mapped[bool] = mapped_column(nullable=False)
    self_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    correct_rate: Mapped[float] = mapped_column(nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    feedback: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    daily_task: Mapped["DailyTask"] = relationship(back_populates="submissions")
    answers: Mapped[list["SubmissionAnswer"]] = relationship(back_populates="submission", cascade="all, delete-orphan")
    mastery_records: Mapped[list["MasteryRecord"]] = relationship(back_populates="submission")


class SubmissionAnswer(Base):
    __tablename__ = "submission_answers"
    __table_args__ = (
        UniqueConstraint("submission_id", "exercise_id", name="uq_submission_exercise_answer"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id", ondelete="CASCADE"), nullable=False)
    user_answer: Mapped[str] = mapped_column(Text, nullable=False)
    is_correct: Mapped[bool] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    submission: Mapped["Submission"] = relationship(back_populates="answers")
    exercise: Mapped["Exercise"] = relationship(back_populates="submission_answers")


class MasteryRecord(Base):
    __tablename__ = "mastery_records"
    __table_args__ = (
        CheckConstraint("old_score >= 0 AND old_score <= 100", name="ck_mastery_old_score_range"),
        CheckConstraint("new_score >= 0 AND new_score <= 100", name="ck_mastery_new_score_range"),
        CheckConstraint("score >= 0 AND score <= 100", name="ck_mastery_score_range"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_mastery_confidence_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    knowledge_point_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    submission_id: Mapped[Optional[int]] = mapped_column(ForeignKey("submissions.id", ondelete="SET NULL"))
    old_score: Mapped[float] = mapped_column(Float, nullable=False)
    new_score: Mapped[float] = mapped_column(Float, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    change_reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="mastery_records")
    knowledge_point: Mapped["KnowledgePoint"] = relationship(back_populates="mastery_records")
    submission: Mapped[Optional["Submission"]] = relationship(back_populates="mastery_records")


class AgentTrace(Base):
    __tablename__ = "agent_traces"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    plan_id: Mapped[Optional[int]] = mapped_column(ForeignKey("study_plans.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[Optional[int]] = mapped_column(ForeignKey("daily_tasks.id", ondelete="SET NULL"), index=True)
    step: Mapped[str] = mapped_column(String(120), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False)
    reason_summary: Mapped[str] = mapped_column(Text, nullable=False)
    input_summary: Mapped[str] = mapped_column(Text, nullable=False)
    output_summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[TraceStatus] = mapped_column(String(32), default=TraceStatus.SUCCESS.value, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    execution_mode: Mapped[str] = mapped_column(String(32), default="rule", nullable=False)
    provider: Mapped[Optional[str]] = mapped_column(String(80))
    model_name: Mapped[Optional[str]] = mapped_column(String(120))
    fallback_reason: Mapped[Optional[str]] = mapped_column(Text)
    request_id: Mapped[Optional[str]] = mapped_column(String(80))
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_char_count: Mapped[Optional[int]] = mapped_column(Integer)
    output_char_count: Mapped[Optional[int]] = mapped_column(Integer)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    plan: Mapped[Optional["StudyPlan"]] = relationship(back_populates="traces")
    task: Mapped[Optional["DailyTask"]] = relationship(back_populates="traces")
