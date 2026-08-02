from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agent.submission_orchestrator import SubmissionFlowError, SubmissionOrchestrator
from app.core.database import get_db
from app.models.schemas import (
    AdjustedTaskRead,
    MasteryUpdateRead,
    SubmissionAnswerRead,
    TaskSubmissionCreate,
    TaskSubmissionResponse,
    WeakKnowledgePointRead,
)


router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.post("/{task_id}/submit", response_model=TaskSubmissionResponse)
def submit_task(task_id: int, payload: TaskSubmissionCreate, db: Session = Depends(get_db)) -> TaskSubmissionResponse:
    try:
        result = SubmissionOrchestrator(db).submit_task(task_id=task_id, payload=payload)
    except SubmissionFlowError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="failed to submit task") from exc

    return TaskSubmissionResponse(
        submission_id=result.submission.id,
        task_id=result.submission.task_id,
        completed=result.submission.completed,
        correct_rate=result.submission.correct_rate,
        answer_results=[
            SubmissionAnswerRead(
                exercise_id=item.exercise.id,
                is_correct=item.result.is_correct,
                evaluation_reason=item.result.evaluation_reason,
            )
            for item in result.answer_evaluations
        ],
        mastery_updates=[
            MasteryUpdateRead(
                knowledge_point_id=item.knowledge_point_id,
                knowledge_point_title=item.knowledge_point_title,
                old_score=item.old_score,
                new_score=item.new_score,
                score_change=item.score_change,
                correct_count=item.correct_count,
                total_count=item.total_count,
                change_reason=item.change_reason,
            )
            for item in result.mastery_updates
        ],
        weak_knowledge_points=[
            WeakKnowledgePointRead(
                id=item.id,
                title=item.title,
                mastery_score=item.mastery_score,
                current_correct_rate=item.current_correct_rate,
                reason=item.reason,
            )
            for item in result.weak_points
        ],
        adjustment_summary=result.adjustment_summary,
        adjusted_tasks=[
            AdjustedTaskRead(
                id=task.id,
                task_date=task.task_date,
                title=task.title,
                status=task.status,
                adjustment_reason=task.adjustment_reason,
            )
            for task in result.adjusted_tasks
        ],
        trace=result.trace,
    )
