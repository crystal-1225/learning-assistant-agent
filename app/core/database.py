from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy import inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()

if settings.database_url.startswith("sqlite:///"):
    db_path = Path(settings.database_url.replace("sqlite:///", "", 1))
    db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_db_and_tables() -> None:
    from app.models import entities  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_agent_trace_columns()


def _ensure_agent_trace_columns() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "agent_traces" in table_names:
        _ensure_sqlite_columns(
            "agent_traces",
            {
                "task_id": "INTEGER",
                "execution_mode": "VARCHAR(32) NOT NULL DEFAULT 'rule'",
                "provider": "VARCHAR(80)",
                "model_name": "VARCHAR(120)",
                "fallback_reason": "TEXT",
                "request_id": "VARCHAR(80)",
                "retry_count": "INTEGER NOT NULL DEFAULT 0",
                "input_char_count": "INTEGER",
                "output_char_count": "INTEGER",
                "prompt_tokens": "INTEGER",
                "completion_tokens": "INTEGER",
                "total_tokens": "INTEGER",
            },
        )
    if "exercises" in table_names:
        _ensure_sqlite_columns("exercises", {"question_type": "VARCHAR(32) NOT NULL DEFAULT 'short_answer'"})
    if "mastery_records" in table_names:
        _ensure_sqlite_columns(
            "mastery_records",
            {
                "user_id": "INTEGER NOT NULL DEFAULT 1",
                "score": "FLOAT NOT NULL DEFAULT 0",
                "confidence": "FLOAT NOT NULL DEFAULT 0",
                "updated_at": "DATETIME",
            },
        )
    if "submission_answers" in table_names:
        _ensure_sqlite_columns(
            "submission_answers",
            {"evaluation_reason": "TEXT NOT NULL DEFAULT ''"},
        )


def _ensure_sqlite_columns(table_name: str, columns: dict[str, str]) -> None:
    inspector = inspect(engine)
    existing = {column["name"] for column in inspector.get_columns(table_name)}
    with engine.begin() as connection:
        for name, ddl in columns.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {name} {ddl}"))
