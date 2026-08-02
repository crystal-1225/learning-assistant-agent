from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
import gradio as gr
from demo.app import build_app
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.courses import router as courses_router
from app.api.plans import router as plans_router
from app.api.tasks import router as tasks_router
from app.api.users import router as users_router
from app.core.config import get_settings
from app.core.database import SessionLocal, create_db_and_tables
from app.core.errors import register_error_handlers


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_db_and_tables()
    yield


app = FastAPI(title="智学环 Agent Backend", version="0.1.0", lifespan=lifespan)
demo_app = build_app()

app = gr.mount_gradio_app(
    app,
    demo_app,
    path="/demo"
)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
register_error_handlers(app)
app.include_router(users_router)
app.include_router(courses_router)
app.include_router(plans_router)
app.include_router(tasks_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    db: Session = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        database = "error"
    finally:
        db.close()
    return {"status": "ok" if database == "ok" else "error", "database": database, "service": "zhixuehuan-agent-backend"}
