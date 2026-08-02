from datetime import date
from pathlib import Path
from typing import Any

import gradio as gr

from demo.api_client import DemoApiClient, DemoApiError
from demo.formatters import (
    extract_session_from_creation,
    format_create_plan_result,
    format_dashboard,
    format_dashboard_error,
    format_error_markdown,
    format_health_markdown,
    format_plan,
    format_submission_result,
    format_today_task,
    format_trace,
    summarize_execution_modes,
    update_session_from_plan,
    update_session_from_submission,
    update_session_from_today_task,
    update_session_from_trace,
)


DASHBOARD_CSS = """
#dashboard-output .dashboard-shell {
    max-width: 1240px;
    margin: 0 auto;
    color: #e2e8f0;
}
#dashboard-output .dashboard-hero {
    background: linear-gradient(125deg, rgba(30, 41, 59, 0.96), rgba(30, 64, 175, 0.56));
    border: 1px solid rgba(147, 197, 253, 0.30);
    border-radius: 16px;
    padding: 24px;
    margin-bottom: 20px;
}
#dashboard-output .dashboard-eyebrow {
    color: #93c5fd;
    font-size: 0.85rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    margin: 0 0 6px;
}
#dashboard-output .dashboard-hero h2 {
    color: #f8fafc;
    margin: 0 0 8px;
}
#dashboard-output .dashboard-course {
    color: #bfdbfe;
    font-size: 1.12rem;
    font-weight: 600;
    margin: 0 0 10px;
}
#dashboard-output .dashboard-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 8px 18px;
    color: #cbd5e1;
    font-size: 0.92rem;
}
#dashboard-output .dashboard-section-title {
    color: #f8fafc;
    font-size: 1.06rem;
    margin: 0 0 10px;
}
#dashboard-output .dashboard-metrics {
    display: grid;
    grid-template-columns: repeat(5, minmax(130px, 1fr));
    gap: 12px;
    margin-bottom: 20px;
}
#dashboard-output .dashboard-metric,
#dashboard-output .dashboard-card {
    background: rgba(30, 41, 59, 0.82);
    border: 1px solid rgba(148, 163, 184, 0.28);
    border-radius: 12px;
}
#dashboard-output .dashboard-metric {
    padding: 14px;
}
#dashboard-output .dashboard-metric span {
    color: #94a3b8;
    display: block;
    font-size: 0.86rem;
}
#dashboard-output .dashboard-metric strong {
    color: #f8fafc;
    display: block;
    font-size: 1.55rem;
    margin-top: 6px;
}
#dashboard-output .dashboard-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(290px, 1fr));
    gap: 12px;
    margin-bottom: 20px;
}
#dashboard-output .dashboard-card {
    padding: 18px;
    min-height: 142px;
}
#dashboard-output .dashboard-card h3 {
    color: #f8fafc;
    font-size: 1rem;
    margin: 0 0 12px;
}
#dashboard-output .dashboard-card strong { color: #93c5fd; }
#dashboard-output .dashboard-card ul { margin: 0; padding-left: 20px; }
#dashboard-output .dashboard-card p { line-height: 1.65; margin: 6px 0; }
#dashboard-output .dashboard-mastery-row {
    align-items: center;
    display: grid;
    gap: 8px;
    grid-template-columns: minmax(88px, 1fr) auto 42px;
}
#dashboard-output .dashboard-progress {
    color: #60a5fa;
    font-family: monospace;
    letter-spacing: 1px;
}
#dashboard-output .dashboard-health {
    font-size: 0.86rem;
    margin: 8px 2px 0;
}
#dashboard-output .dashboard-health-online { color: #86efac; }
#dashboard-output .dashboard-health-offline { color: #fca5a5; }
@media (max-width: 900px) {
    #dashboard-output .dashboard-metrics { grid-template-columns: repeat(2, minmax(130px, 1fr)); }
}
"""

DEMO_CSS = Path(__file__).with_name("style.css").read_text(encoding="utf-8")

def empty_session() -> dict[str, Any]:
    return {
        "user_id": None,
        "user_name": None,
        "course_id": None,
        "plan_id": None,
        "task_id": None,
        "exercises": [],
        "latest_submission_id": None,
        "latest_submission_task_id": None,
        "latest_correct_rate": None,
        "latest_weak_points": [],
        "latest_adjustment_summary": None,
        "latest_adjusted_tasks": [],
        "latest_plan_data": None,
        "latest_trace_data": [],
        "selected_trace_filter": {},
    }


def check_health(state: dict | None) -> tuple[str, str, dict[str, Any]]:
    session = state or empty_session()
    client = DemoApiClient()
    try:
        health = client.health()
        return "🟢 **后端在线**", format_health_markdown(health, client.base_url), session
    except DemoApiError:
        details = (
            "#### 系统状态\n\n"
            f"- 后端地址：`{client.base_url}`\n"
            "- 服务状态：**不可用**\n"
            "- 数据库状态：**未知**\n"
            "- 服务名称：`暂无数据`"
        )
        return "🔴 **后端离线**", details, session


def create_learning_plan(
    state: dict[str, Any] | None,
    user_name: str,
    course_title: str,
    goal: str,
    start_date: str,
    end_date: str,
    daily_minutes: float | int,
    material_text: str,
) -> tuple[str, str, dict[str, Any]]:
    session = state or empty_session()
    validation_error = _validate_create_inputs(
        user_name=user_name,
        course_title=course_title,
        goal=goal,
        start_date=start_date,
        end_date=end_date,
        daily_minutes=daily_minutes,
        material_text=material_text,
    )
    client = DemoApiClient()
    if validation_error:
        return _status_markdown("error", validation_error), format_error_markdown(validation_error, client.base_url), session

    payload = {
        "course_title": course_title.strip(),
        "goal": goal.strip(),
        "start_date": start_date.strip(),
        "end_date": end_date.strip(),
        "daily_minutes": int(daily_minutes),
        "material_text": material_text.strip(),
    }

    try:
        user = client.create_user(user_name.strip())
        user_id = int(user["id"])
        creation = client.create_course_from_text({"user_id": user_id, **payload})
    except (DemoApiError, KeyError, TypeError, ValueError) as exc:
        message = str(exc) or "创建学习计划失败，请检查后端服务和输入内容。"
        return _status_markdown("error", message), format_error_markdown(message, client.base_url), session

    new_session = extract_session_from_creation(creation, user_id)
    new_session["user_name"] = str(user.get("name") or user_name.strip())
    mode_summary = summarize_execution_modes(creation)
    return (
        _status_markdown("success", f"学习计划创建成功，执行模式：{mode_summary}"),
        format_create_plan_result(creation, client.base_url),
        new_session,
    )


def refresh_dashboard(state: dict[str, Any] | None) -> tuple[str, str, dict[str, Any]]:
    session = state or empty_session()
    client = DemoApiClient()
    try:
        health = client.health()
    except DemoApiError:
        health = None

    plan_id = session.get("plan_id")
    if not plan_id:
        status = "success" if health and health.get("status") == "ok" else "error"
        return _dashboard_sync_status(status == "success"), format_dashboard(session, health=health), session

    try:
        plan_data = client.get_plan(int(plan_id))
        today_data = client.get_today_task(int(plan_id))
        traces = client.get_trace(int(plan_id))
    except (DemoApiError, KeyError, TypeError, ValueError):
        message = "刷新学习概览失败，请检查后端服务后重试。"
        return _dashboard_sync_status(False), format_dashboard_error(message, health), session

    new_session = update_session_from_plan(session, plan_data)
    new_session = update_session_from_trace(new_session, traces, {})
    new_session = update_session_from_today_task(new_session, today_data)
    return (
        _dashboard_sync_status(True),
        format_dashboard(new_session, plan_data, today_data, traces, health),
        new_session,
    )


def load_today_task(state: dict[str, Any] | None) -> tuple[str, str, dict[str, Any], str, str, str]:
    session = state or empty_session()
    plan_id = session.get("plan_id")
    client = DemoApiClient()
    if not plan_id:
        message = "当前 Session 中没有 plan_id，请先创建学习计划。"
        return _status_markdown("error", message), format_error_markdown(message, client.base_url), session, "", "", ""

    try:
        today = client.get_today_task(int(plan_id))
    except DemoApiError as exc:
        message = _friendly_api_message(str(exc))
        return _status_markdown("error", message), format_error_markdown(message, client.base_url), session, "", "", ""

    new_session = update_session_from_today_task(session, today)
    exercises = new_session.get("exercises") or []
    if today.get("status") == "all_completed":
        return _status_markdown("success", "所有任务已完成。"), format_today_task(today, client.base_url), new_session, "", "", ""
    return (
        _status_markdown("success", f"今日任务加载成功，共 {len(exercises)} 道练习。"),
        format_today_task(today, client.base_url),
        new_session,
        "",
        "",
        "",
    )


def submit_current_task(
    state: dict[str, Any] | None,
    answer_1: str,
    answer_2: str,
    answer_3: str,
    self_rating: float | int,
    completed: bool,
    notes: str,
) -> tuple[str, str, dict[str, Any]]:
    session = state or empty_session()
    task_id = session.get("task_id")
    exercises = session.get("exercises") or []
    client = DemoApiClient()
    if not task_id:
        message = "当前没有已加载的任务，请先加载今日任务。"
        return _status_markdown("error", message), format_error_markdown(message, client.base_url), session
    if len(exercises) < 1:
        message = "当前任务没有可提交的练习，请重新加载今日任务。"
        return _status_markdown("error", message), format_error_markdown(message, client.base_url), session

    validation_error = _validate_submission_inputs([answer_1, answer_2, answer_3], self_rating, len(exercises))
    if validation_error:
        return _status_markdown("error", validation_error), format_error_markdown(validation_error, client.base_url), session

    answers = [
        {"exercise_id": exercise["id"], "user_answer": answer.strip()}
        for exercise, answer in zip(exercises[:3], [answer_1, answer_2, answer_3], strict=False)
    ]
    try:
        submission = client.submit_task(
            int(task_id),
            completed=bool(completed),
            answers=answers,
            self_rating=int(self_rating),
            notes=notes,
        )
    except DemoApiError as exc:
        message = _friendly_api_message(str(exc))
        return _status_markdown("error", message), format_error_markdown(message, client.base_url), session

    new_session = update_session_from_submission(session, submission)
    return (
        _status_markdown("success", "答案提交成功，反馈已生成。"),
        format_submission_result(submission, client.base_url),
        new_session,
    )


def load_full_plan(state: dict[str, Any] | None) -> tuple[str, str, dict[str, Any]]:
    session = state or empty_session()
    plan_id = session.get("plan_id")
    client = DemoApiClient()
    if not plan_id:
        message = "当前 Session 中没有 plan_id，请先创建学习计划。"
        return _status_markdown("error", message), format_error_markdown(message, client.base_url), session
    try:
        plan_data = client.get_plan(int(plan_id))
    except DemoApiError as exc:
        message = _friendly_api_message(str(exc))
        return _status_markdown("error", message), format_error_markdown(message, client.base_url), session
    new_session = update_session_from_plan(session, plan_data)
    return _status_markdown("success", "完整学习计划已刷新。"), format_plan(plan_data, client.base_url), new_session


def load_agent_trace(
    state: dict[str, Any] | None,
    tool_name: str,
    status: str,
    execution_mode: str,
) -> tuple[str, str, dict[str, Any]]:
    session = state or empty_session()
    plan_id = session.get("plan_id")
    client = DemoApiClient()
    selected_filter = {"tool_name": tool_name or "", "status": status or "", "execution_mode": execution_mode or ""}
    if not plan_id:
        message = "当前 Session 中没有 plan_id，请先创建学习计划。"
        return _status_markdown("error", message), format_error_markdown(message, client.base_url), update_session_from_trace(session, [], selected_filter)

    api_status = status if status in {"success", "failed"} else ""
    api_tool_name = "" if tool_name in ("", "全部") else tool_name.strip()
    try:
        traces = client.get_trace(int(plan_id), status=api_status or None, tool_name=api_tool_name or None)
    except DemoApiError as exc:
        message = _friendly_api_message(str(exc))
        return _status_markdown("error", message), format_error_markdown(message, client.base_url), update_session_from_trace(session, [], selected_filter)

    filtered_traces = _filter_trace_by_execution_mode(traces, execution_mode)
    new_session = update_session_from_trace(session, filtered_traces, selected_filter)
    return (
        _status_markdown("success", f"执行轨迹已刷新，共 {len(filtered_traces)} 条。"),
        format_trace(filtered_traces),
        new_session,
    )


def fill_example_data() -> tuple[str, str, str, str, str, int, str]:
    return (
        "陈晗",
        "数据结构（C语言版）",
        "在14天内系统掌握顺序表、链表、栈和队列的基本原理、核心操作与C语言实现，并能够独立完成基础算法题。",
        "2026-08-01",
        "2026-08-14",
        60,
        "课程内容包括数据结构基本概念、时间复杂度、顺序表、单链表、栈、队列及基础应用。"
        "学习重点为理解逻辑结构与存储结构的关系，掌握插入、删除、查找等基本操作，并能够使用C语言完成核心代码实现。",
    )


def clear_create_form() -> tuple[str, str, str, str, str, int, str, str, str]:
    return (
        "",
        "",
        "",
        "",
        "",
        40,
        "",
        _status_markdown("idle", "已清空表单。"),
        "### 空状态\n\n填写信息后点击“创建学习计划”。",
    )


def build_app() -> gr.Blocks:
    with gr.Blocks(
        title="大学生学习助手 Agent",
        fill_width=True,
        elem_id="learning-assistant-app",
    ) as demo:
        gr.HTML(f"<style>{DASHBOARD_CSS}\n{DEMO_CSS}</style>")
        session_state = gr.State(empty_session())

        health_output = gr.Markdown(
            "🟡 **正在检查后端状态**",
            elem_classes=["backend-status-output"],
        )
        with gr.Accordion(
            "▼ 查看系统状态",
            open=False,
            elem_classes=["system-status-accordion"],
        ):
            with gr.Row(elem_classes=["backend-status-row"]):
                health_button = gr.Button(
                    "重新检查",
                    variant="secondary",
                    elem_classes=["secondary-action"],
                )
            health_details_output = gr.Markdown(
                "正在获取系统状态……",
                elem_classes=["backend-status-details"],
            )

        health_event = health_button.click(
            fn=check_health,
            inputs=[session_state],
            outputs=[health_output, health_details_output, session_state],
            show_progress="full",
        )
        initial_health_event = demo.load(
            fn=check_health,
            inputs=[session_state],
            outputs=[health_output, health_details_output, session_state],
            show_progress="full",
        )

        with gr.Tabs(elem_id="main-navigation"):
            with gr.Tab("🏠 学习概览"):
                with gr.Row():
                    refresh_dashboard_button = gr.Button("刷新概览", variant="primary")
                dashboard_status = gr.Markdown(
                    "⏳ 正在同步学习状态",
                    elem_classes=["dashboard-sync-status"],
                )
                with gr.Row():
                    with gr.Column():
                        with gr.Group():
                            dashboard_output = gr.Markdown(
                                format_dashboard(empty_session(), health=None),
                                elem_id="dashboard-output",
                            )
                health_event.then(
                    fn=refresh_dashboard,
                    inputs=[session_state],
                    outputs=[dashboard_status, dashboard_output, session_state],
                    show_progress="hidden",
                )
                initial_health_event.then(
                    fn=refresh_dashboard,
                    inputs=[session_state],
                    outputs=[dashboard_status, dashboard_output, session_state],
                    show_progress="hidden",
                )

            with gr.Tab("📝 创建学习计划"):
                with gr.Row():
                    user_name = gr.Textbox(label="用户名称", placeholder="例如：演示用户")
                    course_title = gr.Textbox(label="课程名称", placeholder="例如：高等数学")
                goal = gr.Textbox(label="学习目标", placeholder="例如：3天复习极限，准备课堂小测")
                with gr.Row():
                    start_date = gr.Textbox(label="开始日期", placeholder="YYYY-MM-DD")
                    end_date = gr.Textbox(label="结束日期", placeholder="YYYY-MM-DD")
                    daily_minutes = gr.Number(label="每日学习分钟数", value=40, precision=0, minimum=1)
                material_text = gr.Textbox(label="课程笔记文本", lines=8, placeholder="粘贴课程笔记、课件要点或复习资料。")

                with gr.Row():
                    create_button = gr.Button("创建学习计划", variant="primary")
                    clear_button = gr.Button("清空")
                    example_button = gr.Button("示例数据")

                create_status = gr.Markdown(_status_markdown("idle", "等待创建学习计划。"))
                create_output = gr.Markdown("### 空状态\n\n填写信息后点击“创建学习计划”。")

            with gr.Tab("📚 今日任务"):
                load_task_button = gr.Button("加载今日任务", variant="primary")
                task_status = gr.Markdown(_status_markdown("idle", "尚未加载今日任务。"))
                task_output = gr.Markdown("### 未加载任务\n\n创建学习计划后，点击“加载今日任务”。")

                with gr.Row():
                    answer_1 = gr.Textbox(label="第 1 题答案", lines=3)
                    answer_2 = gr.Textbox(label="第 2 题答案", lines=3)
                    answer_3 = gr.Textbox(label="第 3 题答案", lines=3)
                with gr.Row():
                    self_rating = gr.Slider(label="自评分", minimum=1, maximum=5, value=3, step=1)
                    completed = gr.Checkbox(label="已完成今日任务", value=True)
                notes = gr.Textbox(label="学习备注", lines=3, placeholder="可以记录不熟悉的地方。")
                submit_button = gr.Button("提交答案并生成反馈", variant="primary")
                submission_status = gr.Markdown(_status_markdown("idle", "尚未提交答案。"))
                submission_output = gr.Markdown("### 未提交\n\n加载今日任务并填写答案后提交。")

            with gr.Tab("📅 学习计划"):
                refresh_plan_button = gr.Button("刷新完整学习计划", variant="primary")
                plan_status = gr.Markdown(_status_markdown("idle", "尚未加载完整学习计划。"))
                plan_output = gr.Markdown("### 未加载\n\n创建学习计划后，点击“刷新完整学习计划”。")

            with gr.Tab("🤖 Agent 执行轨迹"):
                with gr.Row():
                    trace_tool_filter = gr.Textbox(label="按工具筛选", placeholder="例如：content_parser，留空表示全部")
                    trace_status_filter = gr.Dropdown(label="按状态筛选", choices=["全部", "success", "failed"], value="全部")
                    trace_mode_filter = gr.Dropdown(label="按执行模式筛选", choices=["全部", "rule", "llm", "fallback_rule"], value="全部")
                refresh_trace_button = gr.Button("刷新执行轨迹", variant="primary")
                trace_status = gr.Markdown(_status_markdown("idle", "尚未加载执行轨迹。"))
                trace_output = gr.Markdown("### 未加载\n\n创建学习计划后，点击“刷新执行轨迹”。")

        gr.HTML(
            "<div class=\"product-footer\">"
            "<strong>University Learning Agent</strong>"
            "<span>Powered by FastAPI · Gradio</span>"
            "</div>"
        )

        example_button.click(
            fn=fill_example_data,
            inputs=[],
            outputs=[user_name, course_title, goal, start_date, end_date, daily_minutes, material_text],
            show_progress="hidden",
        )
        clear_button.click(
            fn=clear_create_form,
            inputs=[],
            outputs=[
                user_name,
                course_title,
                goal,
                start_date,
                end_date,
                daily_minutes,
                material_text,
                create_status,
                create_output,
            ],
            show_progress="hidden",
        )
        create_event = create_button.click(
            fn=create_learning_plan,
            inputs=[session_state, user_name, course_title, goal, start_date, end_date, daily_minutes, material_text],
            outputs=[create_status, create_output, session_state],
            show_progress="full",
            concurrency_limit=1,
        )
        create_event.then(
            fn=refresh_dashboard,
            inputs=[session_state],
            outputs=[dashboard_status, dashboard_output, session_state],
            show_progress="full",
        )
        load_task_event = load_task_button.click(
            fn=load_today_task,
            inputs=[session_state],
            outputs=[task_status, task_output, session_state, answer_1, answer_2, answer_3],
            show_progress="full",
            concurrency_limit=1,
        )
        load_task_event.then(
            fn=refresh_dashboard,
            inputs=[session_state],
            outputs=[dashboard_status, dashboard_output, session_state],
            show_progress="full",
        )
        submit_event = submit_button.click(
            fn=submit_current_task,
            inputs=[session_state, answer_1, answer_2, answer_3, self_rating, completed, notes],
            outputs=[submission_status, submission_output, session_state],
            show_progress="full",
            concurrency_limit=1,
        )
        submit_event.then(
            fn=refresh_dashboard,
            inputs=[session_state],
            outputs=[dashboard_status, dashboard_output, session_state],
            show_progress="full",
        )
        refresh_dashboard_button.click(
            fn=refresh_dashboard,
            inputs=[session_state],
            outputs=[dashboard_status, dashboard_output, session_state],
            show_progress="full",
            concurrency_limit=1,
        )
        refresh_plan_button.click(
            fn=load_full_plan,
            inputs=[session_state],
            outputs=[plan_status, plan_output, session_state],
            show_progress="full",
            concurrency_limit=1,
        )
        refresh_trace_button.click(
            fn=load_agent_trace,
            inputs=[session_state, trace_tool_filter, trace_status_filter, trace_mode_filter],
            outputs=[trace_status, trace_output, session_state],
            show_progress="full",
            concurrency_limit=1,
        )
    return demo


def _validate_create_inputs(
    *,
    user_name: str,
    course_title: str,
    goal: str,
    start_date: str,
    end_date: str,
    daily_minutes: float | int,
    material_text: str,
) -> str | None:
    if not user_name or not user_name.strip():
        return "用户名称不能为空。"
    if not course_title or not course_title.strip():
        return "课程名称不能为空。"
    if not goal or not goal.strip():
        return "学习目标不能为空。"
    if not material_text or not material_text.strip():
        return "课程笔记不能为空。"
    try:
        minutes = int(daily_minutes)
    except (TypeError, ValueError):
        return "每日学习分钟数必须是大于 0 的整数。"
    if minutes <= 0:
        return "每日学习分钟数必须大于 0。"
    try:
        start = date.fromisoformat(start_date.strip())
        end = date.fromisoformat(end_date.strip())
    except (AttributeError, ValueError):
        return "日期格式必须是 YYYY-MM-DD。"
    if end < start:
        return "结束日期不得早于开始日期。"
    return None


def _validate_submission_inputs(answers: list[str], self_rating: float | int, expected_count: int) -> str | None:
    try:
        rating = int(self_rating)
    except (TypeError, ValueError):
        return "自评分必须是 1 到 5 的整数。"
    if rating < 1 or rating > 5:
        return "自评分必须在 1 到 5 之间。"
    selected_answers = answers[: max(1, min(expected_count, 3))]
    if not selected_answers or any(not answer or not answer.strip() for answer in selected_answers):
        return "请填写所有练习题答案后再提交。"
    return None


def _friendly_api_message(message: str) -> str:
    if "TASK_ALREADY_SUBMITTED" in message or "already submitted" in message or "已提交" in message:
        return "该学习任务已经提交，请勿重复提交。"
    if "NOT_FOUND" in message or "not found" in message or "HTTP 404" in message:
        return "没有找到对应任务或计划，请重新加载或重新创建学习计划。"
    if "VALIDATION" in message or "HTTP 422" in message:
        return f"提交内容校验失败：{message}"
    return message


def _filter_trace_by_execution_mode(traces: list[dict[str, Any]], execution_mode: str) -> list[dict[str, Any]]:
    if execution_mode not in {"rule", "llm", "fallback_rule"}:
        return traces
    return [trace for trace in traces if trace.get("execution_mode") == execution_mode]


def _status_markdown(status: str, message: str) -> str:
    labels = {
        "idle": "空闲",
        "loading": "创建中",
        "success": "成功",
        "error": "错误",
    }
    return f"### 状态：{labels.get(status, status)}\n\n{message}"


def _dashboard_sync_status(success: bool) -> str:
    if success:
        return "✅ **已同步最新学习状态**\n\n<span class=\"dashboard-status-meta\">状态：成功</span>"
    return "❌ **后端连接失败，请检查服务**\n\n<span class=\"dashboard-status-meta\">状态：错误</span>"


if __name__ == "__main__":
    build_app().launch(
        server_name="127.0.0.1",
        server_port=7860,
        footer_links=[],
    )
