from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agent.orchestrator import AgentOrchestrator
from app.core.database import get_db
from app.llm.client import get_llm_client
from app.models.entities import User
from app.models.schemas import CourseCreationResponse, CourseFromTextCreate


router = APIRouter(prefix="/api/courses", tags=["courses"])


@router.post("/from-text", response_model=CourseCreationResponse)
def create_course_from_text(payload: CourseFromTextCreate, db: Session = Depends(get_db)) -> CourseCreationResponse:
    user = db.get(User, payload.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    try:
        result = AgentOrchestrator(db, llm_client=get_llm_client()).create_course_plan_from_text(
            user=user,
            course_title=payload.course_title,
            goal=payload.goal,
            start_date=payload.start_date,
            end_date=payload.end_date,
            daily_minutes=payload.daily_minutes,
            material_text=payload.material_text,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="failed to create course plan") from exc

    return CourseCreationResponse(
        course=result.course,
        plan=result.plan,
        knowledge_points=result.knowledge_points,
        today_task=result.today_task,
        trace=result.trace,
    )
