import io

from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.entities import AgentTrace, Material

DOCX_LINES = [
    "课程内容包括数据结构基本概念、时间复杂度、顺序表、单链表、栈、队列及基础应用。",
    "学习重点为理解逻辑结构与存储结构的关系，掌握插入、删除、查找等基本操作，并能够使用C语言完成核心代码实现。",
]


def make_docx() -> bytes:
    buf = io.BytesIO()
    doc = Document()
    for line in DOCX_LINES:
        doc.add_paragraph(line)
    doc.save(buf)
    return buf.getvalue()


def create_user(client: TestClient) -> int:
    response = client.post("/api/users", json={"name": "文件测试用户"})
    assert response.status_code == 200
    return response.json()["id"]


def form_fields(user_id: int, **overrides: str) -> dict[str, str]:
    fields = {
        "user_id": str(user_id),
        "course_title": "数据结构（C语言版）",
        "goal": "3天复习数据结构基础",
        "start_date": "2026-07-11",
        "end_date": "2026-07-13",
        "daily_minutes": "40",
    }
    fields.update(overrides)
    return fields


def test_upload_docx_creates_plan(client: TestClient, db_session: Session) -> None:
    user_id = create_user(client)
    response = client.post(
        "/api/courses/from-file",
        data=form_fields(user_id),
        files={
            "file": (
                "notes.docx",
                make_docx(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["course"]["title"] == "数据结构（C语言版）"
    assert data["knowledge_points"]
    titles = [point["title"] for point in data["knowledge_points"]]
    assert titles[:6] == ["数据结构基本概念", "时间复杂度", "顺序表", "单链表", "栈", "队列"]

    trace_tools = {trace["tool_name"] for trace in data["trace"]}
    assert "document_parser" in trace_tools
    assert trace_tools >= {"goal_analyzer", "content_parser", "plan_generator", "task_generator", "exercise_generator"}

    material = db_session.query(Material).filter(Material.course_id == data["course"]["id"]).one()
    assert material.filename == "notes.docx"
    assert "数据结构基本概念" in material.content_text


def test_upload_with_supplementary_text_is_merged(client: TestClient, db_session: Session) -> None:
    user_id = create_user(client)
    response = client.post(
        "/api/courses/from-file",
        data=form_fields(user_id, material_text="补充：重点复习链表指针操作。"),
        files={"file": ("notes.docx", make_docx(), "application/octet-stream")},
    )
    assert response.status_code == 200, response.text
    material = db_session.query(Material).filter(Material.course_id == response.json()["course"]["id"]).one()
    assert "补充：重点复习链表指针操作" in material.content_text


def test_upload_unsupported_extension_is_rejected(client: TestClient) -> None:
    user_id = create_user(client)
    response = client.post(
        "/api/courses/from-file",
        data=form_fields(user_id),
        files={"file": ("notes.txt", b"plain text", "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"


def test_upload_renamed_file_is_rejected(client: TestClient) -> None:
    user_id = create_user(client)
    response = client.post(
        "/api/courses/from-file",
        data=form_fields(user_id),
        files={"file": ("notes.pdf", make_docx(), "application/pdf")},
    )
    assert response.status_code == 400
    assert "不支持的文件格式" in response.json()["error"]["message"]


def test_upload_empty_file_is_rejected(client: TestClient) -> None:
    user_id = create_user(client)
    response = client.post(
        "/api/courses/from-file",
        data=form_fields(user_id),
        files={"file": ("empty.docx", b"", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "文件" in response.json()["error"]["message"]


def test_upload_too_large_is_rejected(client: TestClient, monkeypatch) -> None:
    from app.api import courses as courses_module

    monkeypatch.setattr(
        courses_module,
        "get_settings",
        lambda: Settings(max_file_mb=1),
    )
    user_id = create_user(client)
    oversized = b"x" * (1024 * 1024 + 100)
    response = client.post(
        "/api/courses/from-file",
        data=form_fields(user_id),
        files={"file": ("big.docx", oversized, "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "1MB" in response.json()["error"]["message"]


def test_upload_invalid_user_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/courses/from-file",
        data=form_fields(999),
        files={"file": ("notes.docx", make_docx(), "application/octet-stream")},
    )
    assert response.status_code == 404


def test_upload_invalid_dates_return_422(client: TestClient) -> None:
    user_id = create_user(client)
    response = client.post(
        "/api/courses/from-file",
        data=form_fields(user_id, start_date="2026-07-13", end_date="2026-07-11"),
        files={"file": ("notes.docx", make_docx(), "application/octet-stream")},
    )
    assert response.status_code == 422


def test_upload_response_does_not_leak_answers(client: TestClient) -> None:
    user_id = create_user(client)
    response = client.post(
        "/api/courses/from-file",
        data=form_fields(user_id),
        files={"file": ("notes.docx", make_docx(), "application/octet-stream")},
    )
    assert response.status_code == 200, response.text
    text = str(response.json())
    assert "standard_answer" not in text
    assert "explanation" not in text
    assert "答案应包含" not in text


def test_upload_creates_document_parser_trace(client: TestClient, db_session: Session) -> None:
    user_id = create_user(client)
    response = client.post(
        "/api/courses/from-file",
        data=form_fields(user_id),
        files={"file": ("notes.docx", make_docx(), "application/octet-stream")},
    )
    assert response.status_code == 200, response.text
    plan_id = response.json()["plan"]["id"]
    trace = db_session.query(AgentTrace).filter(
        AgentTrace.plan_id == plan_id,
        AgentTrace.tool_name == "document_parser",
    ).one()
    assert trace.execution_mode == "rule"
    assert "notes.docx" in trace.input_summary
    assert "抽取" in trace.output_summary
