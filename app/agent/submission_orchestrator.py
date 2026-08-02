from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.agent.trace import TraceRecorder
from app.models.entities import (
    AgentTrace,
    DailyTask,
    Exercise,
    KnowledgePoint,
    MasteryRecord,
    StudyPlan,
    Submission,
    SubmissionAnswer,
    TaskStatus,
)
from app.models.schemas import TaskSubmissionCreate
from app.tools import answer_evaluator, progress_evaluator, replanner, weak_point_detector
from app.tools.answer_evaluator import EvaluationResult
from app.tools.progress_evaluator import KnowledgePointPerformance, MasteryUpdate
from app.tools.replanner import ReplanResult
from app.tools.weak_point_detector import WeakKnowledgePoint


class SubmissionFlowError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class AnswerEvaluation:
    exercise: Exercise
    user_answer: str
    result: EvaluationResult


@dataclass
class TaskSubmissionResult:
    submission: Submission
    answer_evaluations: list[AnswerEvaluation]
    mastery_updates: list[MasteryUpdate]
    weak_points: list[WeakKnowledgePoint]
    adjustment_summary: str
    adjusted_tasks: list[DailyTask]
    trace: list[AgentTrace]


class SubmissionOrchestrator:
    def __init__(self, db: Session) -> None:
        self.db = db

    def submit_task(self, *, task_id: int, payload: TaskSubmissionCreate) -> TaskSubmissionResult:
        recorder = TraceRecorder()
        try:
            task = self._load_task(task_id)
            if task is None:
                raise SubmissionFlowError(404, "task not found")

            exercises = recorder.run(
                step="validate_submission",
                tool_name="validate_submission",
                reason_summary="确认任务、练习归属和重复提交规则。",
                input_summary=f"任务ID：{task_id}；提交答案数：{len(payload.answers)}。",
                output_summary=lambda result: f"验证通过，匹配 {len(result)} 道练习。",
                func=lambda: self._validate_submission(task, payload),
                task_id=task.id,
            )

            answer_evaluations = recorder.run(
                step="answer_evaluator",
                tool_name="answer_evaluator",
                reason_summary="使用确定性规则对用户答案进行标准化和自动判题。",
                input_summary=f"待判题数量：{len(exercises)}。",
                output_summary=lambda result: (
                    f"完成判题，答对 {sum(1 for item in result if item.result.is_correct)}/{len(result)}。"
                ),
                func=lambda: self._evaluate_answers(exercises, payload),
                task_id=task.id,
            )

            correct_count = sum(1 for item in answer_evaluations if item.result.is_correct)
            correct_rate = round(correct_count / len(answer_evaluations), 2)

            submission = recorder.run(
                step="save_submission",
                tool_name="save_submission",
                reason_summary="保存提交记录和每道题判题结果。",
                input_summary=f"任务ID：{task.id}；正确率：{correct_rate}。",
                output_summary=lambda result: f"保存提交记录 ID={result.id}。",
                func=lambda: self._save_submission(task, payload, answer_evaluations, correct_rate),
                task_id=task.id,
            )

            mastery_updates = recorder.run(
                step="progress_evaluator",
                tool_name="progress_evaluator",
                reason_summary="按知识点正确率、自评和完成状态更新掌握度。",
                input_summary=f"任务ID：{task.id}；整体正确率：{correct_rate}；自评：{payload.self_rating}/5。",
                output_summary=lambda result: f"更新 {len(result)} 个知识点掌握度。",
                func=lambda: self._update_mastery(task, submission, answer_evaluations, payload),
                task_id=task.id,
            )

            weak_points = recorder.run(
                step="weak_point_detector",
                tool_name="weak_point_detector",
                reason_summary="根据掌握度和本次正确率识别薄弱知识点。",
                input_summary=f"掌握度更新数量：{len(mastery_updates)}。",
                output_summary=lambda result: f"识别出 {len(result)} 个薄弱知识点。",
                func=lambda: weak_point_detector.detect_weak_points(mastery_updates),
                task_id=task.id,
            )

            replan_result = recorder.run(
                step="replanner",
                tool_name="replanner",
                reason_summary="把薄弱知识点插入最近的后续未完成任务。",
                input_summary=f"薄弱知识点数量：{len(weak_points)}。",
                output_summary=lambda result: result.adjustment_summary,
                func=lambda: self._adjust_future_tasks(task, weak_points, payload.notes),
                task_id=task.id,
            )

            trace_entities = recorder.to_entities(task.plan_id)
            self.db.add_all(trace_entities)
            self.db.flush()
            trace_ids = [trace.id for trace in trace_entities]
            self.db.commit()
        except SubmissionFlowError:
            self.db.rollback()
            raise
        except (SQLAlchemyError, ValueError, RuntimeError):
            self.db.rollback()
            raise
        except Exception:
            self.db.rollback()
            raise

        return self._load_submission_result(
            submission.id,
            answer_evaluations,
            mastery_updates,
            weak_points,
            replan_result.adjustment_summary,
            replan_result.adjusted_task_ids,
            trace_ids,
        )

    def _load_task(self, task_id: int) -> DailyTask | None:
        return self.db.scalars(
            select(DailyTask)
            .where(DailyTask.id == task_id)
            .options(
                selectinload(DailyTask.plan).selectinload(StudyPlan.course),
                selectinload(DailyTask.exercises).selectinload(Exercise.knowledge_point),
                selectinload(DailyTask.submissions),
                selectinload(DailyTask.knowledge_point_links),
            )
        ).first()

    def _validate_submission(self, task: DailyTask, payload: TaskSubmissionCreate) -> dict[int, Exercise]:
        existing_submission = self.db.scalar(select(Submission.id).where(Submission.task_id == task.id).limit(1))
        if existing_submission is not None:
            raise SubmissionFlowError(409, "task has already been submitted")

        exercise_ids = {answer.exercise_id for answer in payload.answers}
        exercises = self.db.scalars(select(Exercise).where(Exercise.id.in_(exercise_ids))).all()
        exercises_by_id = {exercise.id: exercise for exercise in exercises}

        missing = sorted(exercise_ids - set(exercises_by_id))
        if missing:
            raise SubmissionFlowError(400, f"exercise not found: {missing[0]}")

        wrong_task = [exercise.id for exercise in exercises if exercise.task_id != task.id]
        if wrong_task:
            raise SubmissionFlowError(400, f"exercise does not belong to task: {wrong_task[0]}")

        return exercises_by_id

    def _evaluate_answers(
        self,
        exercises_by_id: dict[int, Exercise],
        payload: TaskSubmissionCreate,
    ) -> list[AnswerEvaluation]:
        evaluations: list[AnswerEvaluation] = []
        for answer in payload.answers:
            exercise = exercises_by_id[answer.exercise_id]
            result = answer_evaluator.evaluate_answer(
                standard_answer=exercise.standard_answer,
                user_answer=answer.user_answer,
                question=exercise.question,
                difficulty=exercise.difficulty,
                question_type=exercise.question_type,
            )
            evaluations.append(AnswerEvaluation(exercise=exercise, user_answer=answer.user_answer, result=result))
        return evaluations

    def _save_submission(
        self,
        task: DailyTask,
        payload: TaskSubmissionCreate,
        answer_evaluations: list[AnswerEvaluation],
        correct_rate: float,
    ) -> Submission:
        feedback = f"本次答对 {sum(1 for item in answer_evaluations if item.result.is_correct)}/{len(answer_evaluations)}。"
        submission = Submission(
            task_id=task.id,
            completed=payload.completed,
            self_rating=payload.self_rating,
            correct_rate=correct_rate,
            notes=payload.notes,
            feedback=feedback,
        )
        self.db.add(submission)
        self.db.flush()

        for item in answer_evaluations:
            self.db.add(
                SubmissionAnswer(
                    submission_id=submission.id,
                    exercise_id=item.exercise.id,
                    user_answer=item.user_answer,
                    is_correct=item.result.is_correct,
                )
            )

        task.status = TaskStatus.COMPLETED.value if payload.completed else TaskStatus.PENDING.value
        self.db.flush()
        return submission

    def _update_mastery(
        self,
        task: DailyTask,
        submission: Submission,
        answer_evaluations: list[AnswerEvaluation],
        payload: TaskSubmissionCreate,
    ) -> list[MasteryUpdate]:
        grouped: dict[int, list[AnswerEvaluation]] = {}
        for item in answer_evaluations:
            grouped.setdefault(item.exercise.knowledge_point_id, []).append(item)

        performances: list[KnowledgePointPerformance] = []
        for knowledge_point_id, items in grouped.items():
            point = items[0].exercise.knowledge_point
            latest = self._latest_mastery(task.plan.course.user_id, knowledge_point_id)
            old_score = latest.score if latest is not None else 20.0
            previous_confidence = latest.confidence if latest is not None else 0.0
            performances.append(
                KnowledgePointPerformance(
                    knowledge_point_id=knowledge_point_id,
                    knowledge_point_title=point.title,
                    old_score=old_score,
                    previous_confidence=previous_confidence,
                    correct_count=sum(1 for item in items if item.result.is_correct),
                    total_count=len(items),
                )
            )

        updates = progress_evaluator.evaluate_progress(
            performances,
            self_rating=payload.self_rating,
            completed=payload.completed,
        )
        for update in updates:
            self.db.add(
                MasteryRecord(
                    user_id=task.plan.course.user_id,
                    knowledge_point_id=update.knowledge_point_id,
                    submission_id=submission.id,
                    old_score=update.old_score,
                    new_score=update.new_score,
                    score=update.new_score,
                    confidence=update.confidence,
                    change_reason=update.change_reason,
                )
            )
        self.db.flush()
        return updates

    def _latest_mastery(self, user_id: int, knowledge_point_id: int) -> MasteryRecord | None:
        return self.db.scalars(
            select(MasteryRecord)
            .where(MasteryRecord.user_id == user_id, MasteryRecord.knowledge_point_id == knowledge_point_id)
            .order_by(MasteryRecord.id.desc())
        ).first()

    def _adjust_future_tasks(
        self,
        task: DailyTask,
        weak_points: list[WeakKnowledgePoint],
        notes: str | None,
    ) -> ReplanResult:
        future_tasks = self.db.scalars(
            select(DailyTask)
            .where(DailyTask.plan_id == task.plan_id, DailyTask.id != task.id)
            .options(selectinload(DailyTask.knowledge_point_links))
        ).all()
        result = replanner.adjust_future_tasks(
            current_task=task,
            future_tasks=list(future_tasks),
            weak_knowledge_points=weak_points,
            notes=notes,
        )
        self.db.flush()
        return result

    def _load_submission_result(
        self,
        submission_id: int,
        answer_evaluations: list[AnswerEvaluation],
        mastery_updates: list[MasteryUpdate],
        weak_points: list[WeakKnowledgePoint],
        adjustment_summary: str,
        adjusted_task_ids: list[int],
        trace_ids: list[int],
    ) -> TaskSubmissionResult:
        submission = self.db.scalars(
            select(Submission)
            .where(Submission.id == submission_id)
            .options(
                selectinload(Submission.daily_task),
                selectinload(Submission.answers).selectinload(SubmissionAnswer.exercise),
            )
        ).one()
        traces = self.db.scalars(
            select(AgentTrace)
            .where(AgentTrace.id.in_(trace_ids))
            .order_by(AgentTrace.id)
        ).all()
        adjusted_tasks = []
        if adjusted_task_ids:
            adjusted_tasks = self.db.scalars(
                select(DailyTask)
                .where(DailyTask.id.in_(adjusted_task_ids))
                .order_by(DailyTask.task_date, DailyTask.id)
            ).all()
        return TaskSubmissionResult(
            submission=submission,
            answer_evaluations=answer_evaluations,
            mastery_updates=mastery_updates,
            weak_points=weak_points,
            adjustment_summary=adjustment_summary,
            adjusted_tasks=list(adjusted_tasks),
            trace=list(traces),
        )
