from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.agent.orchestrator import AgentOrchestrator
from app.core.config import get_settings
from app.core.database import get_db
from app.llm.client import get_llm_client
from app.models.entities import User
from app.models.schemas import CourseCreationResponse, CourseFromFileCreate, CourseFromTextCreate
from app.tools.document_parser import DocumentParseError


router = APIRouter(prefix="/api/courses", tags=["courses"])


@router.post("/from-text", response_model=CourseCreationResponse)
def create_course_from_text(payload: CourseFromTextCreate, db: Session = Depends(get_db)) -> CourseCreationResponse:
    user = _require_user(payload.user_id, db)
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

    return _build_course_creation_response(result)


@router.post("/from-file", response_model=CourseCreationResponse)
async def create_course_from_file(
    user_id: int = Form(...),
    course_title: str = Form(...),
    goal: str = Form(...),
    start_date: date = Form(...),
    end_date: date = Form(...),
    daily_minutes: int = Form(...),
    material_text: str | None = Form(default=None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> CourseCreationResponse:
    try:
        payload = CourseFromFileCreate(
            user_id=user_id,
            course_title=course_title,
            goal=goal,
            start_date=start_date,
            end_date=end_date,
            daily_minutes=daily_minutes,
            material_text=material_text,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="请求参数校验失败") from exc

    user = _require_user(payload.user_id, db)

    # Only the sanitized basename is kept: no client-supplied path is stored.
    filename = Path(file.filename or "").name.strip()
    if not filename:
        raise HTTPException(status_code=400, detail="invalid filename")

    max_bytes = get_settings().max_file_mb * 1024 * 1024
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(status_code=400, detail=f"文件超过 {get_settings().max_file_mb}MB 大小限制")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise HTTPException(status_code=400, detail="文件内容为空")

    try:
        result = AgentOrchestrator(db, llm_client=get_llm_client()).create_course_plan_from_file(
            user=user,
            course_title=payload.course_title,
            goal=payload.goal,
            start_date=payload.start_date,
            end_date=payload.end_date,
            daily_minutes=payload.daily_minutes,
            filename=filename,
            file_bytes=data,
            supplementary_text=payload.material_text or "",
        )
    except DocumentParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="failed to create course plan from file") from exc

    return _build_course_creation_response(result)


def _require_user(user_id: int, db: Session) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return user


def _build_course_creation_response(result) -> CourseCreationResponse:
    return CourseCreationResponse(
        course=result.course,
        plan=result.plan,
        knowledge_points=result.knowledge_points,
        today_task=result.today_task,
        trace=result.trace,
    )
