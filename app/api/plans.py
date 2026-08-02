from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.agent.orchestrator import AgentOrchestrator
from app.core.database import get_db
from app.llm.client import get_llm_client
from app.models.entities import (
    AgentTrace,
    Course,
    DailyTask,
    DailyTaskKnowledgePoint,
    KnowledgePoint,
    MasteryRecord,
    StudyPlan,
    TaskStatus,
)
from app.models.schemas import AgentTraceRead, StudyPlanDetailRead, TodayTaskResponse


router = APIRouter(prefix="/api/plans", tags=["plans"])


@router.get("/{plan_id}", response_model=StudyPlanDetailRead)
def get_plan(plan_id: int, db: Session = Depends(get_db)) -> StudyPlanDetailRead:
    plan = _load_plan(plan_id, db)
    course = db.get(Course, plan.course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="course not found")

    knowledge_points = db.scalars(
        select(KnowledgePoint).where(KnowledgePoint.course_id == plan.course_id).order_by(KnowledgePoint.id)
    ).all()
    mastery_records = db.scalars(
        select(MasteryRecord)
        .join(KnowledgePoint, MasteryRecord.knowledge_point_id == KnowledgePoint.id)
        .where(KnowledgePoint.course_id == plan.course_id)
        .order_by(MasteryRecord.knowledge_point_id, MasteryRecord.id)
    ).all()
    _sort_tasks(plan)
    return StudyPlanDetailRead(
        plan=plan,
        course=course,
        knowledge_points=list(knowledge_points),
        mastery_records=list(mastery_records),
    )


@router.get("/{plan_id}/today", response_model=TodayTaskResponse)
def get_today_task(plan_id: int, db: Session = Depends(get_db)) -> TodayTaskResponse:
    plan = _load_plan(plan_id, db)
    _sort_tasks(plan)
    incomplete = [task for task in plan.daily_tasks if task.status != TaskStatus.COMPLETED.value]
    if not incomplete:
        return TodayTaskResponse(status="all_completed", task=None, message="所有任务已完成")

    today = date.today()
    today_tasks = [task for task in incomplete if task.task_date == today]
    task = sorted(today_tasks or incomplete, key=lambda item: item.task_date)[0]
    if not task.exercises:
        course = db.get(Course, plan.course_id)
        if course is None:
            raise HTTPException(status_code=404, detail="course not found")
        try:
            AgentOrchestrator(db, llm_client=get_llm_client()).ensure_daily_task_exercises(
                plan=plan,
                task=task,
                course=course,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail="failed to generate daily exercises") from exc
    return TodayTaskResponse(status="ok", task=task)


@router.get("/{plan_id}/trace", response_model=list[AgentTraceRead])
def get_plan_trace(
    plan_id: int,
    task_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    tool_name: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[AgentTrace]:
    _ensure_plan_exists(plan_id, db)
    query = select(AgentTrace).where(AgentTrace.plan_id == plan_id)
    if task_id is not None:
        query = query.where(AgentTrace.task_id == task_id)
    if status is not None:
        query = query.where(AgentTrace.status == status)
    if tool_name is not None:
        query = query.where(AgentTrace.tool_name == tool_name)
    return list(db.scalars(query.order_by(AgentTrace.created_at, AgentTrace.id)).all())


def _load_plan(plan_id: int, db: Session) -> StudyPlan:
    plan = db.scalars(
        select(StudyPlan)
        .where(StudyPlan.id == plan_id)
        .options(
            selectinload(StudyPlan.daily_tasks)
            .selectinload(DailyTask.knowledge_point_links)
            .selectinload(DailyTaskKnowledgePoint.knowledge_point),
            selectinload(StudyPlan.daily_tasks).selectinload(DailyTask.exercises),
        )
    ).first()
    if plan is None:
        raise HTTPException(status_code=404, detail="plan not found")
    return plan


def _ensure_plan_exists(plan_id: int, db: Session) -> None:
    if db.get(StudyPlan, plan_id) is None:
        raise HTTPException(status_code=404, detail="plan not found")


def _sort_tasks(plan: StudyPlan) -> None:
    plan.daily_tasks = sorted(plan.daily_tasks, key=lambda task: (task.task_date, task.id))
