from dataclasses import dataclass
from datetime import date
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.agent.trace import TraceRecorder
from app.core.config import get_settings
from app.llm.base import LLMCallMetadata, LLMClient
from app.llm.exceptions import LLMError
from app.llm.prompts import content_prompt, exercise_prompt, goal_prompt
from app.llm.schemas import LLMContentAnalysis, LLMExerciseSet, LLMGoalAnalysis
from app.models.entities import (
    AgentTrace,
    Course,
    DailyTask,
    DailyTaskKnowledgePoint,
    Exercise,
    KnowledgePoint,
    MasteryRecord,
    Material,
    StudyPlan,
    User,
)
from app.tools import content_parser, document_parser, exercise_generator, goal_analyzer, plan_generator, task_generator
from app.tools.document_parser import DocumentParseError
from app.tools.types import ExerciseDraft, GoalSummary, KnowledgePointDraft


T = TypeVar("T")


@dataclass
class CoursePlanResult:
    course: Course
    plan: StudyPlan
    knowledge_points: list[KnowledgePoint]
    today_task: DailyTask
    trace: list[AgentTrace]


@dataclass(frozen=True)
class ToolResult(Generic[T]):
    value: T
    execution_mode: str
    provider: str | None = None
    model_name: str | None = None
    fallback_reason: str | None = None
    call_metadata: LLMCallMetadata | None = None


class AgentOrchestrator:
    def __init__(self, db: Session, llm_client: LLMClient | None = None) -> None:
        self.db = db
        self.llm_client = llm_client

    def create_course_plan_from_text(
        self,
        *,
        user: User,
        course_title: str,
        goal: str,
        start_date,
        end_date,
        daily_minutes: int,
        material_text: str,
        filename: str = "from-text.txt",
    ) -> CoursePlanResult:
        recorder = TraceRecorder()
        return self._create_course_plan_with_recorder(
            recorder,
            user=user,
            course_title=course_title,
            goal=goal,
            start_date=start_date,
            end_date=end_date,
            daily_minutes=daily_minutes,
            material_text=material_text,
            filename=filename,
        )

    def create_course_plan_from_file(
        self,
        *,
        user: User,
        course_title: str,
        goal: str,
        start_date,
        end_date,
        daily_minutes: int,
        filename: str,
        file_bytes: bytes,
        supplementary_text: str = "",
    ) -> CoursePlanResult:
        """Extract text from an uploaded document, then reuse the text chain.

        The original file is never persisted: only the sanitized basename and
        the extracted text reach the database.
        """
        recorder = TraceRecorder()
        parse_result = recorder.run(
            step="解析文档资料",
            tool_name="document_parser",
            reason_summary="从上传文件中抽取课程文本，供知识点解析使用。",
            input_summary=f"文件名：{filename}；文件大小：{len(file_bytes)} 字节。",
            output_summary=lambda result: f"识别格式 {result.file_format}，抽取 {result.char_count} 字符。",
            func=lambda: document_parser.extract_text_from_bytes(filename, file_bytes),
        )
        text = parse_result.text
        if supplementary_text and supplementary_text.strip():
            text = f"{text}\n{supplementary_text.strip()}"
        text = text[: get_settings().max_file_chars]
        return self._create_course_plan_with_recorder(
            recorder,
            user=user,
            course_title=course_title,
            goal=goal,
            start_date=start_date,
            end_date=end_date,
            daily_minutes=daily_minutes,
            material_text=text,
            filename=filename,
        )

    def _create_course_plan_with_recorder(
        self,
        recorder: TraceRecorder,
        *,
        user: User,
        course_title: str,
        goal: str,
        start_date,
        end_date,
        daily_minutes: int,
        material_text: str,
        filename: str,
    ) -> CoursePlanResult:
        try:
            goal_result = recorder.run(
                step="分析学习目标",
                tool_name="goal_analyzer",
                reason_summary="将用户自然语言目标转为可规划的时间和学习强度信息。",
                input_summary=f"目标：{goal[:80]}；日期：{start_date} 至 {end_date}；每天 {daily_minutes} 分钟。",
                output_summary=lambda result: result.value.summary,
                func=lambda: self._analyze_goal(goal, start_date, end_date, daily_minutes),
                metadata=_trace_metadata,
            )
            goal_summary = goal_result.value
            point_result = recorder.run(
                step="解析课程文本",
                tool_name="content_parser",
                reason_summary="从上传资料中抽取第一版可执行知识点。",
                input_summary=f"课程：{course_title}；资料长度：{len(material_text)} 字符。",
                output_summary=lambda result: f"提取 {len(result.value)} 个知识点。",
                func=lambda: self._parse_content(course_title, material_text, goal),
                metadata=_trace_metadata,
            )
            point_drafts = point_result.value
            day_plan_drafts = recorder.run(
                step="制定学习计划",
                tool_name="plan_generator",
                reason_summary="把知识点按日期范围分配为每日计划。",
                input_summary=f"知识点数量：{len(point_drafts)}；计划天数：{goal_summary.total_days}。",
                output_summary=lambda result: f"生成 {len(result)} 天计划。",
                func=lambda: plan_generator.generate_plan(goal_summary, point_drafts),
            )
            task_drafts = recorder.run(
                step="生成每日任务",
                tool_name="task_generator",
                reason_summary="将每日计划转为可保存和展示的任务草案。",
                input_summary=f"每日计划数量：{len(day_plan_drafts)}。",
                output_summary=lambda result: f"生成 {len(result)} 个每日任务草案。",
                func=lambda: task_generator.generate_tasks(day_plan_drafts),
            )

            course = Course(user_id=user.id, title=course_title, description=goal_summary.summary)
            self.db.add(course)
            self.db.flush()

            material = Material(
                course_id=course.id,
                filename=filename,
                content_text=material_text,
                summary=f"已解析出 {len(point_drafts)} 个知识点。",
            )
            self.db.add(material)

            knowledge_points = [
                KnowledgePoint(
                    course_id=course.id,
                    title=draft.title,
                    description=draft.description,
                    difficulty=draft.difficulty,
                )
                for draft in point_drafts
            ]
            self.db.add_all(knowledge_points)
            self.db.flush()

            plan = StudyPlan(
                course_id=course.id,
                goal=goal,
                start_date=start_date,
                end_date=end_date,
                daily_minutes=daily_minutes,
            )
            self.db.add(plan)
            self.db.flush()

            daily_tasks: list[DailyTask] = []
            for draft in task_drafts:
                task = DailyTask(
                    plan_id=plan.id,
                    task_date=draft.task_date,
                    title=draft.title,
                    content=draft.content,
                )
                self.db.add(task)
                self.db.flush()
                for kp_index in draft.knowledge_point_indexes:
                    self.db.add(
                        DailyTaskKnowledgePoint(
                            daily_task_id=task.id,
                            knowledge_point_id=knowledge_points[kp_index].id,
                        )
                    )
                daily_tasks.append(task)

            today_task = daily_tasks[0]
            first_day_indexes = task_drafts[0].knowledge_point_indexes
            first_day_drafts = [point_drafts[index] for index in first_day_indexes]
            course_has_code_context = exercise_generator.has_code_context(point_drafts, course_title)
            exercise_result = recorder.run(
                step="生成首日练习",
                tool_name="exercise_generator",
                reason_summary="为第一天任务生成固定数量的基础练习。",
                input_summary=f"首日关联知识点数量：{len(first_day_drafts)}。",
                output_summary=lambda result: f"生成 {len(result.value)} 道练习题。",
                func=lambda: self._generate_exercises(
                    first_day_drafts,
                    course_title=course_title,
                    day_number=1,
                    code_context=course_has_code_context,
                ),
                task_id=today_task.id,
                metadata=_trace_metadata,
            )
            exercise_drafts = exercise_result.value
            for draft in exercise_drafts:
                source_index = first_day_indexes[draft.knowledge_point_index % len(first_day_indexes)]
                self.db.add(
                    Exercise(
                        task_id=today_task.id,
                        knowledge_point_id=knowledge_points[source_index].id,
                        question=draft.question,
                        standard_answer=draft.standard_answer,
                        explanation=draft.explanation,
                        difficulty=draft.difficulty,
                        question_type=draft.question_type,
                    )
                )

            for point in knowledge_points:
                self.db.add(
                    MasteryRecord(
                        user_id=user.id,
                        knowledge_point_id=point.id,
                        old_score=0,
                        new_score=20,
                        score=20,
                        confidence=0.0,
                        change_reason="创建学习计划时初始化掌握度。",
                    )
                )

            self.db.add_all(recorder.to_entities(plan.id))
            self.db.commit()
        except (SQLAlchemyError, ValueError, RuntimeError):
            self.db.rollback()
            raise
        except Exception:
            self.db.rollback()
            raise

        return self._load_result(plan.id)

    def ensure_daily_task_exercises(
        self,
        *,
        plan: StudyPlan,
        task: DailyTask,
        course: Course,
    ) -> list[Exercise]:
        """Generate and persist exercises once for a task that has none."""
        existing = list(
            self.db.scalars(
                select(Exercise).where(Exercise.task_id == task.id).order_by(Exercise.id)
            ).all()
        )
        if existing:
            return existing

        links = sorted(task.knowledge_point_links, key=lambda link: link.knowledge_point_id)
        task_points = [link.knowledge_point for link in links]
        if not task_points:
            raise ValueError("daily task has no knowledge points")

        point_drafts = [
            KnowledgePointDraft(
                title=point.title,
                description=point.description or "",
                difficulty=point.difficulty,
            )
            for point in task_points
        ]
        course_points = list(
            self.db.scalars(
                select(KnowledgePoint)
                .where(KnowledgePoint.course_id == course.id)
                .order_by(KnowledgePoint.id)
            ).all()
        )
        course_point_drafts = [
            KnowledgePointDraft(
                title=point.title,
                description=point.description or "",
                difficulty=point.difficulty,
            )
            for point in course_points
        ]
        ordered_tasks = sorted(plan.daily_tasks, key=lambda item: (item.task_date, item.id))
        day_number = next(
            (index for index, item in enumerate(ordered_tasks, start=1) if item.id == task.id),
            1,
        )
        code_context = exercise_generator.has_code_context(course_point_drafts, course.title)
        recorder = TraceRecorder()

        try:
            exercise_result = recorder.run(
                step="按需生成每日练习",
                tool_name="exercise_auto_generator",
                reason_summary="今日任务尚无练习，复用 Exercise Generator V3 按需补齐。",
                input_summary=f"第 {day_number} 天；关联知识点数量：{len(point_drafts)}。",
                output_summary=lambda result: f"生成并保存 {len(result.value)} 道练习题。",
                func=lambda: self._generate_exercises(
                    point_drafts,
                    course_title=course.title,
                    day_number=day_number,
                    code_context=code_context,
                    task_title=f"{task.title}；学习目标：{plan.goal}",
                ),
                task_id=task.id,
                metadata=_trace_metadata,
            )
            generated: list[Exercise] = []
            for draft in exercise_result.value:
                point = task_points[draft.knowledge_point_index]
                exercise = Exercise(
                    task_id=task.id,
                    knowledge_point_id=point.id,
                    question=draft.question,
                    standard_answer=draft.standard_answer,
                    explanation=draft.explanation,
                    difficulty=draft.difficulty,
                    question_type=draft.question_type,
                )
                self.db.add(exercise)
                generated.append(exercise)

            self.db.add_all(recorder.to_entities(plan.id))
            self.db.commit()
            for exercise in generated:
                self.db.refresh(exercise)
            self.db.expire(task, ["exercises"])
            task.exercises
            return generated
        except Exception:
            self.db.rollback()
            raise

    def _analyze_goal(self, goal: str, start_date: date, end_date: date, daily_minutes: int) -> ToolResult[GoalSummary]:
        if self.llm_client is None:
            return ToolResult(goal_analyzer.analyze_goal(goal, start_date, end_date, daily_minutes), "rule")
        try:
            llm_result = self.llm_client.generate_structured(
                prompt=goal_prompt(
                    goal=goal,
                    start_date=start_date.isoformat(),
                    end_date=end_date.isoformat(),
                    daily_minutes=daily_minutes,
                ),
                response_model=LLMGoalAnalysis,
            )
            summary = GoalSummary(
                goal=goal.strip(),
                start_date=start_date,
                end_date=end_date,
                daily_minutes=daily_minutes,
                total_days=(end_date - start_date).days + 1,
                summary=llm_result.summary,
            )
            return ToolResult(summary, "llm", self.llm_client.provider, self.llm_client.model_name, None, self.llm_client.last_call_metadata)
        except (LLMError, ValueError) as exc:
            return ToolResult(
                goal_analyzer.analyze_goal(goal, start_date, end_date, daily_minutes),
                "fallback_rule",
                self.llm_client.provider,
                self.llm_client.model_name,
                exc.__class__.__name__,
                self.llm_client.last_call_metadata,
            )

    def _parse_content(self, course_title: str, material_text: str, goal: str = "") -> ToolResult[list[KnowledgePointDraft]]:
        if self.llm_client is None:
            return ToolResult(content_parser.parse_content(course_title, material_text, learning_goal=goal), "rule")
        try:
            truncated_text = material_text[: get_settings().llm_max_input_chars]
            llm_result = self.llm_client.generate_structured(
                prompt=content_prompt(course_title=course_title, material_text=truncated_text, learning_goal=goal),
                response_model=LLMContentAnalysis,
            )
            points = _sanitize_llm_points(llm_result)
            if not points:
                raise ValueError("LLM returned no valid knowledge points")
            return ToolResult(points, "llm", self.llm_client.provider, self.llm_client.model_name, None, self.llm_client.last_call_metadata)
        except (LLMError, ValueError) as exc:
            return ToolResult(
                content_parser.parse_content(course_title, material_text, learning_goal=goal),
                "fallback_rule",
                self.llm_client.provider,
                self.llm_client.model_name,
                exc.__class__.__name__,
                self.llm_client.last_call_metadata,
            )

    def _generate_exercises(
        self,
        knowledge_points: list[KnowledgePointDraft],
        *,
        course_title: str = "",
        day_number: int = 1,
        code_context: bool | None = None,
        task_title: str = "首日学习任务",
    ) -> ToolResult[list[ExerciseDraft]]:
        if self.llm_client is None:
            return ToolResult(
                exercise_generator.generate_exercises(
                    knowledge_points,
                    count=3,
                    course_title=course_title,
                    day_number=day_number,
                    code_context=code_context,
                ),
                "rule",
            )
        try:
            title_to_index = {point.title: index for index, point in enumerate(knowledge_points)}
            llm_result = self.llm_client.generate_structured(
                prompt=exercise_prompt(
                    task_title=task_title,
                    knowledge_point_titles=[point.title for point in knowledge_points],
                    course_title=course_title,
                    day_number=day_number,
                    code_context=code_context,
                ),
                response_model=LLMExerciseSet,
            )
            drafts: list[ExerciseDraft] = []
            for exercise in llm_result.exercises:
                if exercise.knowledge_point_title not in title_to_index:
                    raise ValueError("LLM exercise cannot be mapped to a known knowledge point")
                drafts.append(
                    ExerciseDraft(
                        knowledge_point_index=title_to_index[exercise.knowledge_point_title],
                        question=exercise.question,
                        standard_answer=exercise.standard_answer,
                        explanation=exercise.explanation,
                        difficulty=exercise.difficulty,
                        question_type=exercise.question_type,
                    )
                )
            drafts = exercise_generator.ensure_unique_exercises(
                drafts,
                knowledge_points,
                count=3,
                expected_difficulty=exercise_generator.difficulty_for_day(day_number),
                code_context=(
                    exercise_generator.has_code_context(knowledge_points, course_title)
                    if code_context is None
                    else code_context
                ),
            )
            return ToolResult(drafts, "llm", self.llm_client.provider, self.llm_client.model_name, None, self.llm_client.last_call_metadata)
        except (LLMError, ValueError) as exc:
            return ToolResult(
                exercise_generator.generate_exercises(
                    knowledge_points,
                    count=3,
                    course_title=course_title,
                    day_number=day_number,
                    code_context=code_context,
                ),
                "fallback_rule",
                self.llm_client.provider,
                self.llm_client.model_name,
                exc.__class__.__name__,
                self.llm_client.last_call_metadata,
            )

    def _load_result(self, plan_id: int) -> CoursePlanResult:
        plan = self.db.scalars(
            select(StudyPlan)
            .where(StudyPlan.id == plan_id)
            .options(
                selectinload(StudyPlan.course),
                selectinload(StudyPlan.daily_tasks)
                .selectinload(DailyTask.knowledge_point_links)
                .selectinload(DailyTaskKnowledgePoint.knowledge_point),
                selectinload(StudyPlan.daily_tasks).selectinload(DailyTask.exercises),
                selectinload(StudyPlan.traces),
            )
        ).one()
        daily_tasks = sorted(plan.daily_tasks, key=lambda task: task.task_date)
        plan.daily_tasks = daily_tasks
        today_task = daily_tasks[0]
        knowledge_points = self.db.scalars(
            select(KnowledgePoint).where(KnowledgePoint.course_id == plan.course_id).order_by(KnowledgePoint.id)
        ).all()
        traces = self.db.scalars(
            select(AgentTrace).where(AgentTrace.plan_id == plan.id).order_by(AgentTrace.id)
        ).all()
        return CoursePlanResult(
            course=plan.course,
            plan=plan,
            knowledge_points=list(knowledge_points),
            today_task=today_task,
            trace=list(traces),
        )


def _trace_metadata(result: ToolResult[object]) -> dict[str, str | None]:
    metadata = getattr(result, "call_metadata", None)
    return {
        "execution_mode": result.execution_mode,
        "provider": result.provider,
        "model_name": result.model_name,
        "fallback_reason": result.fallback_reason,
        "request_id": str(metadata.request_id) if metadata else None,
        "retry_count": str(metadata.retry_count) if metadata else None,
        "input_char_count": str(metadata.input_char_count) if metadata else None,
        "output_char_count": str(metadata.output_char_count) if metadata and metadata.output_char_count is not None else None,
        "prompt_tokens": str(metadata.prompt_tokens) if metadata and metadata.prompt_tokens is not None else None,
        "completion_tokens": str(metadata.completion_tokens) if metadata and metadata.completion_tokens is not None else None,
        "total_tokens": str(metadata.total_tokens) if metadata and metadata.total_tokens is not None else None,
    }


def _sanitize_llm_points(content: LLMContentAnalysis) -> list[KnowledgePointDraft]:
    seen: set[str] = set()
    points: list[KnowledgePointDraft] = []
    for point in content.knowledge_points:
        for title in content_parser.normalize_knowledge_point_title(point.title):
            key = title.lower()
            if key in seen:
                continue
            seen.add(key)
            points.append(
                KnowledgePointDraft(
                    title=title,
                    description=point.description.strip(),
                    difficulty=point.difficulty,
                    importance=point.importance,
                    source_hint=point.source_hint.strip(),
                )
            )
            if len(points) == content_parser.MAX_KNOWLEDGE_POINTS:
                return points
    return points
