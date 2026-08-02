from html import escape
from typing import Any


def format_health_markdown(data: dict[str, Any], base_url: str) -> str:
    status = data.get("status", "unknown")
    database = data.get("database", "unknown")
    service = data.get("service", "unknown")
    return (
        "### 后端状态\n\n"
        f"- 后端地址：`{base_url}`\n"
        f"- 服务状态：**{status}**\n"
        f"- 数据库状态：**{database}**\n"
        f"- 服务名称：`{service}`"
    )


def format_error_markdown(message: str, base_url: str) -> str:
    return (
        "### 连接失败\n\n"
        f"- 后端地址：`{base_url}`\n"
        f"- 错误信息：{message}\n\n"
        "请先启动 FastAPI 后端，并确认 `ZHIXUEHUAN_BACKEND_URL` 配置正确。"
    )


def contains_answer_leak(text: str) -> bool:
    blocked = ["standard_answer", "explanation", "答案应包含", "本题用于检查"]
    return any(item in text for item in blocked)


def format_create_plan_result(data: dict[str, Any], base_url: str) -> str:
    course = data.get("course") or {}
    plan = data.get("plan") or {}
    knowledge_points = data.get("knowledge_points") or []
    today_task = data.get("today_task") or {}
    exercises = today_task.get("exercises") or []
    traces = data.get("trace") or []

    lines = [
        "### 创建成功",
        "",
        f"- 后端地址：`{base_url}`",
        f"- 课程：**{_safe(course.get('title'))}**",
        f"- 学习目标：{_safe(plan.get('goal'))}",
        f"- 起止日期：`{_safe(plan.get('start_date'))}` 至 `{_safe(plan.get('end_date'))}`",
        f"- 每日学习时长：**{_safe(plan.get('daily_minutes'))} 分钟**",
        f"- 计划 ID：`{_safe(plan.get('id'))}`",
        "",
        "#### 知识点",
    ]
    if knowledge_points:
        for point in knowledge_points:
            title = _safe(point.get("title"))
            difficulty = _safe(point.get("difficulty"))
            description = _safe(point.get("description"))
            lines.append(f"- **{title}**（{difficulty}）：{description}")
    else:
        lines.append("- 暂无知识点")

    lines.extend(
        [
            "",
            "#### 今日任务",
            f"- 标题：**{_safe(today_task.get('title'))}**",
            f"- 内容：{_safe(today_task.get('content'))}",
            "",
            "#### 练习题",
        ]
    )
    if exercises:
        for index, exercise in enumerate(exercises, start=1):
            question_type = _safe(exercise.get("question_type"))
            difficulty = _safe(exercise.get("difficulty"))
            question = _safe(exercise.get("question"))
            lines.append(f"{index}. [{question_type}/{difficulty}] {question}")
    else:
        lines.append("- 暂无练习题")

    lines.extend(["", "#### Agent 执行轨迹摘要"])
    if traces:
        for trace in traces:
            mode = _safe(trace.get("execution_mode"))
            tool = _safe(trace.get("tool_name"))
            status = _safe(trace.get("status"))
            duration = _safe(trace.get("duration_ms"))
            fallback = trace.get("fallback_reason")
            fallback_text = f"，回退原因：{_safe(fallback)}" if fallback else ""
            lines.append(f"- `{mode}` · {tool} · {status} · {duration}ms{fallback_text}")
    else:
        lines.append("- 暂无执行轨迹")

    return "\n".join(lines)


def summarize_execution_modes(data: dict[str, Any]) -> str:
    traces = data.get("trace") or []
    modes = []
    for trace in traces:
        mode = trace.get("execution_mode")
        if mode and mode not in modes:
            modes.append(str(mode))
    return "、".join(modes) if modes else "unknown"


def extract_session_from_creation(data: dict[str, Any], user_id: int) -> dict[str, Any]:
    course = data.get("course") or {}
    plan = data.get("plan") or {}
    today_task = data.get("today_task") or {}
    return {
        "user_id": user_id,
        "course_id": course.get("id"),
        "plan_id": plan.get("id"),
        "task_id": today_task.get("id"),
        "exercises": today_task.get("exercises") or [],
        "latest_submission_id": None,
        "latest_correct_rate": None,
        "latest_weak_points": [],
        "latest_adjustment_summary": None,
    }


def format_today_task(data: dict[str, Any], base_url: str) -> str:
    status = data.get("status")
    task = data.get("task")
    message = data.get("message")
    if status == "all_completed":
        return f"### 今日任务\n\n所有任务已完成。{_safe(message) if message else ''}"
    if not isinstance(task, dict):
        return f"### 今日任务\n\n暂无可展示任务。{_safe(message) if message else ''}"

    knowledge_points = task.get("knowledge_points") or []
    exercises = task.get("exercises") or []
    lines = [
        "### 今日任务已加载",
        "",
        f"- 后端地址：`{base_url}`",
        f"- 任务标题：**{_safe(task.get('title'))}**",
        f"- 任务日期：`{_safe(task.get('task_date'))}`",
        f"- 任务状态：`{_safe(task.get('status'))}`",
        f"- 学习内容：{_safe(task.get('content'))}",
        "",
        "#### 关联知识点",
    ]
    if knowledge_points:
        for point in knowledge_points:
            lines.append(f"- **{_safe(point.get('title'))}**（{_safe(point.get('difficulty'))}）")
    else:
        lines.append("- 暂无关联知识点")

    lines.extend(["", "#### 练习题"])
    if exercises:
        for index, exercise in enumerate(exercises, start=1):
            lines.append(
                f"{index}. [{_safe(exercise.get('question_type'))}/{_safe(exercise.get('difficulty'))}] "
                f"{_safe(exercise.get('question'))}"
            )
    else:
        lines.append("- 暂无练习题")
    return "\n".join(lines)


def format_submission_result(data: dict[str, Any], base_url: str) -> str:
    correct_rate = float(data.get("correct_rate") or 0)
    answer_results = data.get("answer_results") or []
    correct_count = sum(1 for item in answer_results if item.get("is_correct"))
    total_count = len(answer_results)
    weak_points = data.get("weak_knowledge_points") or []
    adjustment_summary = data.get("adjustment_summary") or "暂无调整。"
    adjusted_tasks = data.get("adjusted_tasks") or []
    traces = data.get("trace") or []
    lines = [
        "### 提交成功",
        "",
        f"- 后端地址：`{base_url}`",
        f"- 提交 ID：`{_safe(data.get('submission_id'))}`",
        f"- 正确题数：**{correct_count}**",
        f"- 总题数：**{total_count}**",
        f"- 总体正确率：**{_format_percent(correct_rate)}**",
        f"- 完成状态：`{_safe(data.get('completed'))}`",
        "",
        _result_interpretation(correct_rate, weak_points, adjustment_summary),
        "",
        "#### 逐题判定",
    ]

    if answer_results:
        for index, result in enumerate(answer_results, start=1):
            marker = "正确" if result.get("is_correct") else "需订正"
            lines.append(f"{index}. **{marker}**：{_safe(result.get('evaluation_reason'))}")
    else:
        lines.append("- 暂无判题结果")

    lines.extend(["", "#### 掌握度变化"])
    mastery_updates = data.get("mastery_updates") or []
    if mastery_updates:
        for item in mastery_updates:
            lines.append(
                f"- **{_safe(item.get('knowledge_point_title'))}**："
                f"{_format_score(item.get('old_score'))} -> {_format_score(item.get('new_score'))} "
                f"({_format_delta(item.get('score_change'))})；{_safe(item.get('change_reason'))}"
            )
    else:
        lines.append("- 暂无掌握度变化")

    lines.extend(["", "#### 薄弱知识点"])
    if weak_points:
        for point in weak_points:
            lines.append(
                f"- **{_safe(point.get('title'))}**：掌握度 {_format_score(point.get('mastery_score'))}，"
                f"本轮正确率 {_format_percent(float(point.get('current_correct_rate') or 0))}；{_safe(point.get('reason'))}"
            )
    else:
        lines.append("- 本轮未发现明显薄弱点")

    adjustment_status = "已触发" if adjusted_tasks else "未触发"
    lines.extend(["", "#### 后续计划调整", f"- 是否触发计划调整：**{adjustment_status}**", f"> { _safe(adjustment_summary) }"])
    if adjusted_tasks:
        for task in adjusted_tasks:
            lines.append(
                f"- 已调整任务：**{_safe(task.get('title'))}**（{_safe(task.get('task_date'))}，"
                f"{_safe(task.get('adjustment_reason'))}）"
            )
    else:
        lines.append("- 被调整任务：暂无数据")

    execution_mode = traces[-1].get("execution_mode") if traces else None
    lines.extend(["", f"- 本次执行模式：`{_safe(execution_mode)}`", "", "#### 本次 Agent 执行轨迹摘要"])
    if traces:
        for trace in traces:
            fallback = trace.get("fallback_reason")
            fallback_text = f"，回退原因：{_safe(fallback)}" if fallback else ""
            lines.append(
                f"- `{_safe(trace.get('execution_mode'))}` · {_safe(trace.get('tool_name'))} · "
                f"{_safe(trace.get('status'))} · {_safe(trace.get('duration_ms'))}ms{fallback_text}"
            )
    else:
        lines.append("- 暂无执行轨迹")
    return "\n".join(lines)


def format_dashboard(
    state: dict[str, Any] | None,
    plan_data: dict[str, Any] | None = None,
    today_data: dict[str, Any] | None = None,
    traces: list[dict[str, Any]] | None = None,
    health: dict[str, Any] | None = None,
) -> str:
    """Format Dashboard 2.0 with only public API data and local session state."""
    session = state or {}
    if not session.get("plan_id"):
        hero = (
            "<section class=\"dashboard-hero\">"
            "<div class=\"dashboard-hero-main\">"
            "<div class=\"dashboard-brand\">"
            "<span class=\"dashboard-brand-logo\" aria-hidden=\"true\">🎓</span>"
            "<div><p class=\"dashboard-eyebrow\">大学生学习助手 Agent</p>"
            "<p class=\"dashboard-subtitle\">基于学习诊断与动态规划的主动学习平台</p></div>"
            "</div>"
            "<h2>欢迎使用大学生学习助手 Agent</h2>"
            "<p class=\"dashboard-hero-copy\">创建你的第一个学习计划开始体验。</p>"
            "<span class=\"dashboard-legacy-copy\">当前尚未创建学习计划，请先进入“创建学习计划”完成设置。</span>"
            "</div>"
            "<aside class=\"dashboard-hero-side\"><span class=\"dashboard-mode-badge\">主动学习 · 动态规划</span></aside>"
            "</section>"
        )
        return _dashboard_shell(hero, "", health)

    data = plan_data or {}
    plan = data.get("plan") if isinstance(data.get("plan"), dict) else {}
    course = data.get("course") if isinstance(data.get("course"), dict) else {}
    tasks = plan.get("daily_tasks") if isinstance(plan.get("daily_tasks"), list) else []
    knowledge_points = data.get("knowledge_points") if isinstance(data.get("knowledge_points"), list) else []
    mastery_records = data.get("mastery_records") if isinstance(data.get("mastery_records"), list) else []
    trace_items = traces or []
    total_tasks = len(tasks)
    completed_tasks = sum(1 for task in tasks if task.get("status") == "completed")
    pending_tasks = sum(1 for task in tasks if task.get("status") == "pending")
    adjusted_tasks = sum(1 for task in tasks if task.get("status") == "adjusted")
    completion_rate = completed_tasks / total_tasks if total_tasks else None
    api_today_task = today_data.get("task") if isinstance(today_data, dict) and isinstance(today_data.get("task"), dict) else None
    submitted_task_id = session.get("latest_submission_task_id")
    submitted_task = next((task for task in tasks if task.get("id") == submitted_task_id), None)
    plan_completed = bool(total_tasks and completed_tasks == total_tasks)
    today_task = submitted_task if submitted_task and submitted_task.get("status") == "completed" else api_today_task
    if today_task:
        next_task = _dashboard_next_task_after(
            tasks,
            exclude_task_id=today_task.get("id"),
            after_date=today_task.get("task_date"),
        )
    else:
        next_task = _dashboard_next_task_after(tasks)
    latest_scores = _dashboard_latest_scores(mastery_records)
    weak_points = session.get("latest_weak_points") if isinstance(session.get("latest_weak_points"), list) else []
    adjustment = _dashboard_adjustment(session, tasks)
    latest_trace = _dashboard_latest_trace(trace_items)

    hero = (
        "<section class=\"dashboard-hero\">"
        "<div class=\"dashboard-hero-main\">"
        "<div class=\"dashboard-brand\">"
        "<span class=\"dashboard-brand-logo\" aria-hidden=\"true\">🎓</span>"
        "<div><p class=\"dashboard-eyebrow\">大学生学习助手 Agent</p>"
        "<p class=\"dashboard-subtitle\">基于学习诊断与动态规划的主动学习平台</p></div>"
        "</div>"
        f"<h2>欢迎回来，{_dashboard_value(session.get('user_name'))} 👋</h2>"
        "<p class=\"dashboard-welcome-note\">今天继续完成你的学习计划。</p>"
        "<div class=\"dashboard-current-plan\">"
        f"<div><span>当前课程</span><strong>{_dashboard_value(course.get('title'))}</strong></div>"
        f"<div><span>当前学习目标</span><strong>{_dashboard_goal_summary(plan.get('goal'))}</strong></div>"
        "</div>"
        "<div class=\"dashboard-meta\">"
        f"<span>📅 {_dashboard_value(plan.get('start_date'))} 至 {_dashboard_value(plan.get('end_date'))}</span>"
        "</div></div>"
        "<aside class=\"dashboard-hero-side\">"
        "<span class=\"dashboard-mode-badge\">主动学习 · 动态规划</span>"
        f"<span class=\"dashboard-plan-badge\">{_dashboard_plan_status(plan.get('status'))}</span>"
        "</aside></section>"
    )
    metrics = "".join(
        _dashboard_metric(label, value)
        for label, value in [
            ("计划总任务数", str(total_tasks)),
            ("已完成任务数", str(completed_tasks)),
            ("待完成任务数", str(pending_tasks)),
            ("已调整任务数", str(adjusted_tasks)),
            ("计划完成率", _dashboard_percent(completion_rate)),
        ]
    )
    today_status = "已完成" if today_task is submitted_task else None
    today_content = _dashboard_today_card(
        today_task,
        today_data,
        plan.get("daily_minutes"),
        status_override=today_status,
    )
    next_content = _dashboard_next_card(
        next_task,
        plan_completed=plan_completed,
        after_current=bool(today_task and today_task.get("status") != "completed"),
    )
    advice = _dashboard_advice(weak_points, adjusted_tasks, pending_tasks, total_tasks, completed_tasks)
    advice_content = (
        "<div class=\"agent-advice\">"
        f"<div class=\"agent-advice__feedback\"><span>最近学习反馈</span><strong>{_dashboard_learning_feedback(session)}</strong></div>"
        "<h4>最近薄弱知识点</h4>"
        f"{_dashboard_weak_points(weak_points)}"
        f"<div class=\"agent-advice__message\"><span aria-hidden=\"true\">💡</span><p><strong>Agent 建议</strong>{_dashboard_value(advice)}</p></div>"
        "</div>"
    )
    decisions = _dashboard_decisions(adjustment, latest_trace)
    advice_content += f"<div class=\"agent-decision\"><h4>最近决策</h4>{decisions}</div>"
    content = (
        f"<section><h3 class=\"dashboard-section-title\">学习进度</h3><div class=\"dashboard-metrics\">{metrics}</div></section>"
        "<div class=\"dashboard-grid dashboard-task-grid\">"
        f"{_dashboard_card('今日学习', today_content)}"
        f"{_dashboard_card('下一任务', next_content)}"
        "</div>"
        "<div class=\"dashboard-grid dashboard-diagnosis-grid\">"
        f"{_dashboard_card('知识掌握度', _dashboard_mastery(knowledge_points, latest_scores))}"
        f"{_dashboard_card('Agent 学习建议', advice_content)}"
        "</div>"
    )
    return _dashboard_shell(hero, content, health)


def format_dashboard_error(message: str, health: dict[str, Any] | None = None) -> str:
    safe_message = _dashboard_value(message)
    hero = "<section class=\"dashboard-hero\"><p class=\"dashboard-eyebrow\">学习概览</p><h2>暂时无法刷新概览</h2></section>"
    content = _dashboard_card("刷新提示", f"<p>{safe_message}</p>")
    return _dashboard_shell(hero, content, health)


def _dashboard_shell(hero: str, content: str, health: dict[str, Any] | None) -> str:
    return "\n".join(
        [
            "<div class=\"dashboard-shell\">",
            hero,
            content,
            _dashboard_health_line(health),
            "</div>",
        ]
    )


def _dashboard_card(title: str, content: str) -> str:
    return f"<section class=\"dashboard-card\"><h3>{escape(title)}</h3>{content}</section>"


def _dashboard_metric(label: str, value: str) -> str:
    icons = {
        "计划总任务数": "🗂️",
        "已完成任务数": "✅",
        "待完成任务数": "⏳",
        "已调整任务数": "🔄",
        "计划完成率": "🎯",
    }
    return (
        "<section class=\"dashboard-metric\">"
        f"<span class=\"dashboard-metric__icon\" aria-hidden=\"true\">{icons.get(label, '📌')}</span>"
        f"<span class=\"dashboard-metric__label\">{escape(label)}</span>"
        f"<strong class=\"dashboard-metric__value\">{escape(value)}</strong>"
        "</section>"
    )


def _dashboard_health_line(health: dict[str, Any] | None) -> str:
    if health and health.get("status") == "ok":
        return "<p class=\"dashboard-health dashboard-health-online\">● 后端在线</p>"
    return "<p class=\"dashboard-health dashboard-health-offline\">● 后端离线，请检查服务</p>"


def _dashboard_today_status(today_data: dict[str, Any] | None) -> str | None:
    if not isinstance(today_data, dict):
        return None
    if today_data.get("status") == "all_completed":
        return "全部任务已完成"
    task = today_data.get("task")
    return _dashboard_task_status(task.get("status")) if isinstance(task, dict) else None


def _dashboard_next_task(tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    return _dashboard_next_task_after(tasks)


def _dashboard_next_task_after(
    tasks: list[dict[str, Any]],
    *,
    exclude_task_id: Any = None,
    after_date: Any = None,
) -> dict[str, Any] | None:
    incomplete = [
        task
        for task in tasks
        if task.get("status") != "completed"
        and task.get("id") != exclude_task_id
        and (after_date is None or str(task.get("task_date") or "") > str(after_date))
    ]
    if not incomplete:
        return None
    return min(incomplete, key=lambda task: (str(task.get("task_date") or ""), int(task.get("id") or 0)))


def _dashboard_latest_scores(records: list[dict[str, Any]]) -> dict[int, float]:
    scores: dict[int, float] = {}
    for record in records:
        point_id = record.get("knowledge_point_id")
        if point_id is None:
            continue
        try:
            scores[int(point_id)] = float(record.get("score", record.get("new_score")))
        except (TypeError, ValueError):
            continue
    return scores


def _dashboard_mastery(knowledge_points: list[dict[str, Any]], scores: dict[int, float]) -> str:
    if not knowledge_points or not scores:
        return "<p class=\"dashboard-empty\">暂无掌握度记录</p>"
    lines = ["<div class=\"dashboard-mastery-list\">"]
    for point in knowledge_points:
        point_id = point.get("id")
        score = scores.get(int(point_id)) if point_id is not None else None
        if score is None:
            lines.append(
                "<div class=\"dashboard-mastery-row dashboard-mastery-row--empty\">"
                f"<span class=\"dashboard-mastery-name\">{_dashboard_value(point.get('title'))}</span>"
                "<span class=\"dashboard-mastery-value\">暂无数据</span></div>"
            )
            continue
        bounded_score = min(100, max(0, float(score)))
        level = "high" if bounded_score >= 70 else "medium" if bounded_score >= 40 else "low"
        lines.append(
            "<div class=\"dashboard-mastery-row\">"
            f"<span class=\"dashboard-mastery-name\">{_dashboard_value(point.get('title'))}</span>"
            "<span class=\"dashboard-progress\">"
            f"<span class=\"dashboard-progress-fill dashboard-progress-fill--{level}\" style=\"width:{bounded_score:.0f}%\"></span>"
            f"<span class=\"dashboard-progress-legacy\">{_dashboard_progress_bar(score)}</span>"
            "</span>"
            f"<strong class=\"dashboard-mastery-value\">{_dashboard_score_percent(score)}</strong></div>"
        )
    lines.append("</div>")
    return "".join(lines)


def _dashboard_weak_points(points: list[dict[str, Any]]) -> str:
    if not points:
        return "<p class=\"dashboard-empty\">暂无薄弱点（暂无数据）</p>"
    lines = ["<div class=\"weak-point-list\">"]
    for point in points[:3]:
        title = _dashboard_value(point.get("title"))
        score = _dashboard_score_percent(point.get("mastery_score"))
        reason = _dashboard_value(point.get("reason"))
        lines.append(
            "<div class=\"weak-point-chip\">"
            f"<strong>{title}</strong><span>{score}</span><small>{reason}</small>"
            "</div>"
        )
    lines.append("</div>")
    return "".join(lines)


def _dashboard_adjustment(session: dict[str, Any], tasks: list[dict[str, Any]]) -> str | None:
    summary = session.get("latest_adjustment_summary")
    if isinstance(summary, str) and summary.strip():
        return summary
    adjusted = [task for task in tasks if task.get("adjustment_reason")]
    if not adjusted:
        return None
    latest = max(adjusted, key=lambda task: (str(task.get("task_date") or ""), int(task.get("id") or 0)))
    return latest.get("adjustment_reason")


def _dashboard_traces(traces: list[dict[str, Any]]) -> str:
    if not traces:
        return "<p>暂无数据</p>"
    latest = sorted(traces, key=lambda trace: (str(trace.get("created_at") or ""), int(trace.get("id") or 0)), reverse=True)[:3]
    lines = ["<ul>"]
    for trace in latest:
        mode = _dashboard_value(trace.get("execution_mode"))
        tool = _dashboard_value(trace.get("tool_name"))
        status = _dashboard_value(trace.get("status"))
        lines.append(f"<li>{mode} · {tool} · {status}</li>")
    lines.append("</ul>")
    return "".join(lines)


def _dashboard_latest_trace(traces: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not traces:
        return None
    return max(traces, key=lambda trace: (str(trace.get("created_at") or ""), int(trace.get("id") or 0)))


def _dashboard_today_card(
    task: dict[str, Any] | None,
    today_data: dict[str, Any] | None,
    daily_minutes: Any,
    *,
    status_override: str | None = None,
) -> str:
    if not task:
        status = _dashboard_today_status(today_data)
        return (
            "<div class=\"task-empty\">📭<strong>暂无任务</strong>"
            f"<span>今日任务状态：{_dashboard_value(status)}</span></div>"
        )
    points = task.get("knowledge_points") if isinstance(task.get("knowledge_points"), list) else []
    point_titles = "、".join(_dashboard_value(point.get("title")) for point in points if isinstance(point, dict)) or "暂无数据"
    task_status = _dashboard_value(
        status_override or _dashboard_today_status(today_data) or _dashboard_task_status(task.get("status"))
    )
    minutes = _dashboard_minutes(daily_minutes)
    return (
        f"<p class=\"task-focus-title\">{_dashboard_value(task.get('title'))}</p>"
        "<div class=\"task-detail-grid\">"
        f"<div><span>知识点</span><strong>{point_titles}</strong><small>涉及知识点：{point_titles}</small></div>"
        f"<div><span>预计学习时间</span><strong>{minutes}</strong><small>计划时长：{minutes}</small></div>"
        f"<div><span>状态</span><strong class=\"status-pill\">{task_status}</strong><small>任务状态：{task_status}</small></div>"
        "</div>"
    )


def _dashboard_next_card(
    task: dict[str, Any] | None,
    *,
    plan_completed: bool = False,
    after_current: bool = False,
) -> str:
    if not task:
        if plan_completed:
            return "<div class=\"task-empty\">🎉<strong>当前计划已完成</strong></div>"
        return "<div class=\"task-empty\">📭<strong>暂无任务</strong></div>"
    prefix = "<p class=\"task-next-hint\">完成当前任务后进入：</p>" if after_current else ""
    task_status = _dashboard_task_status(task.get("status"))
    return (
        prefix
        + f"<p class=\"task-focus-title\">{_dashboard_value(task.get('title'))}</p>"
        "<div class=\"task-detail-grid task-detail-grid--next\">"
        f"<div><span>任务日期</span><strong>{_dashboard_value(task.get('task_date'))}</strong><small>任务日期：{_dashboard_value(task.get('task_date'))}</small></div>"
        f"<div><span>状态</span><strong class=\"status-pill\">{task_status}</strong><small>任务状态：{task_status}</small></div>"
        "</div>"
    )


def _dashboard_advice(
    weak_points: list[dict[str, Any]],
    adjusted_tasks: int,
    pending_tasks: int,
    total_tasks: int,
    completed_tasks: int,
) -> str | None:
    if weak_points:
        titles = "、".join(str(point.get("title")).strip() for point in weak_points[:3] if point.get("title"))
        if titles:
            return f"建议优先复习：{titles}，完成补救任务后再继续新内容。"
    if adjusted_tasks:
        return "系统已根据学习反馈调整后续计划，请关注调整后的任务安排。"
    if total_tasks and completed_tasks == total_tasks:
        return "当前计划任务已完成，可以进行阶段复习或创建新的学习计划。"
    if pending_tasks:
        return "当前学习状态正常，建议按计划完成下一项任务。"
    return None


def _dashboard_learning_feedback(session: dict[str, Any]) -> str:
    if session.get("latest_submission_id") is None:
        return "暂无学习反馈"
    correct_rate = session.get("latest_correct_rate")
    try:
        return f"最近提交正确率：{_format_percent(float(correct_rate))}"
    except (TypeError, ValueError):
        return "已提交学习反馈"


def _dashboard_decisions(adjustment: str | None, trace: dict[str, Any] | None) -> str:
    adjustment_text = _dashboard_value(adjustment) if adjustment else "暂无调整"
    if not trace:
        return (
            "<div class=\"agent-decision-grid\">"
            f"<div><span>最近计划调整原因</span><strong>{adjustment_text}</strong><small>最近计划调整原因：{adjustment_text}</small></div>"
            "<div><span>最近 Agent 工具</span><strong>暂无数据</strong><small>最近 Agent 工具：暂无数据</small></div>"
            "<div><span>最近执行模式</span><strong>暂无数据</strong><small>最近执行模式：暂无数据</small></div>"
            "<div><span>最近执行状态</span><strong>暂无数据</strong><small>最近执行状态：暂无数据</small></div>"
            "</div>"
        )
    tool = _dashboard_value(trace.get("tool_name"))
    mode = _dashboard_execution_mode(trace.get("execution_mode"))
    status = _dashboard_trace_status(trace.get("status"))
    return (
        "<div class=\"agent-decision-grid\">"
        f"<div><span>最近计划调整原因</span><strong>{adjustment_text}</strong><small>最近计划调整原因：{adjustment_text}</small></div>"
        f"<div><span>最近 Agent 工具</span><strong>{tool}</strong><small>最近 Agent 工具：{tool}</small></div>"
        f"<div><span>最近执行模式</span><strong>{mode}</strong><small>最近执行模式：{mode}</small></div>"
        f"<div><span>最近执行状态</span><strong>{status}</strong><small>最近执行状态：{status}</small></div>"
        "</div>"
    )


def _dashboard_value(value: Any) -> str:
    if value is None or not str(value).strip():
        return "暂无数据"
    return escape(str(value))


def _dashboard_minutes(value: Any) -> str:
    if value is None:
        return "暂无数据"
    try:
        return f"{int(value)} 分钟"
    except (TypeError, ValueError):
        return "暂无数据"


def _dashboard_percent(value: float | None) -> str:
    if value is None:
        return "暂无数据"
    return f"{value * 100:.0f}%"


def _dashboard_score_percent(value: Any) -> str:
    try:
        return f"{round(min(100, max(0, float(value))))}%"
    except (TypeError, ValueError):
        return "暂无数据"


def _dashboard_progress_bar(value: Any) -> str:
    try:
        score = min(100, max(0, float(value)))
    except (TypeError, ValueError):
        return ""
    filled = min(10, max(0, round(score / 10)))
    return "█" * filled + "░" * (10 - filled)


def _dashboard_goal_summary(value: Any) -> str:
    if value is None or not str(value).strip():
        return "暂无数据"
    text = str(value).strip()
    suffix = "…" if len(text) > 120 else ""
    return escape(text[:120] + suffix)


def _dashboard_plan_status(value: Any) -> str:
    return {"active": "进行中", "completed": "已完成", "archived": "已归档"}.get(str(value), "暂无数据")


def _dashboard_task_status(value: Any) -> str:
    return {"pending": "待完成", "completed": "已完成", "adjusted": "已调整"}.get(str(value), "暂无数据")


def _dashboard_execution_mode(value: Any) -> str:
    return {"rule": "规则模式", "llm": "大模型模式", "fallback_rule": "回退规则模式"}.get(str(value), "暂无数据")


def _dashboard_trace_status(value: Any) -> str:
    return {"success": "成功", "failed": "失败"}.get(str(value), "暂无数据")


def update_session_from_today_task(state: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    session = dict(state)
    task = data.get("task") if isinstance(data, dict) else None
    if isinstance(task, dict):
        session["task_id"] = task.get("id")
        session["exercises"] = task.get("exercises") or []
    return session


def update_session_from_submission(state: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    session = dict(state)
    session["latest_submission_id"] = data.get("submission_id")
    session["latest_submission_task_id"] = data.get("task_id")
    session["latest_correct_rate"] = data.get("correct_rate")
    session["latest_weak_points"] = data.get("weak_knowledge_points") or []
    session["latest_adjustment_summary"] = data.get("adjustment_summary")
    session["latest_adjusted_tasks"] = data.get("adjusted_tasks") or []
    return session


def format_plan(data: dict[str, Any], base_url: str) -> str:
    plan = data.get("plan") or {}
    course = data.get("course") or {}
    knowledge_points = data.get("knowledge_points") or []
    mastery_records = data.get("mastery_records") or []
    daily_tasks = plan.get("daily_tasks") or []
    lines = [
        "### 完整学习计划",
        "",
        f"- 后端地址：`{base_url}`",
        f"- 课程名称：**{_safe(course.get('title'))}**",
        f"- 学习目标：{_safe(plan.get('goal'))}",
        f"- 起止日期：`{_safe(plan.get('start_date'))}` 至 `{_safe(plan.get('end_date'))}`",
        f"- 每日学习分钟数：**{_safe(plan.get('daily_minutes'))} 分钟**",
        "",
        format_mastery_records(knowledge_points, mastery_records),
        "",
        format_daily_tasks(daily_tasks),
    ]
    return "\n".join(lines)


def format_mastery_records(knowledge_points: list[dict[str, Any]], mastery_records: list[dict[str, Any]]) -> str:
    latest_scores: dict[int, float] = {}
    for record in mastery_records:
        point_id = record.get("knowledge_point_id")
        if point_id is not None:
            latest_scores[int(point_id)] = float(record.get("score", record.get("new_score", 0)) or 0)

    lines = ["#### 知识点与掌握度"]
    if not knowledge_points:
        lines.append("- 暂无知识点")
        return "\n".join(lines)
    for point in knowledge_points:
        point_id = point.get("id")
        score = latest_scores.get(int(point_id), 0.0) if point_id is not None else 0.0
        lines.append(
            f"- **{_safe(point.get('title'))}**（{_safe(point.get('difficulty'))}）："
            f"掌握度 {_format_mastery_score(score)}；{_safe(point.get('description'))}"
        )
    return "\n".join(lines)


def format_daily_tasks(daily_tasks: list[dict[str, Any]]) -> str:
    lines = ["#### 每日任务"]
    if not daily_tasks:
        lines.append("- 暂无每日任务")
        return "\n".join(lines)
    for task in sorted(daily_tasks, key=lambda item: (str(item.get("task_date") or ""), int(item.get("id") or 0))):
        status = _task_status_label(str(task.get("status") or ""))
        adjusted = bool(task.get("adjustment_reason"))
        current_marker = "【当前任务】" if str(task.get("status")) == "pending" else ""
        completed_marker = "【已完成】" if str(task.get("status")) == "completed" else ""
        adjusted_marker = "【已调整】" if adjusted else ""
        markers = " ".join(item for item in [current_marker, completed_marker, adjusted_marker] if item)
        kp_titles = "、".join(_safe(point.get("title")) for point in task.get("knowledge_points") or []) or "暂无"
        lines.extend(
            [
                "",
                f"- {markers} `{_safe(task.get('task_date'))}` **{_safe(task.get('title'))}**",
                f"  - 状态：{status}",
                f"  - 内容：{_safe(task.get('content'))}",
                f"  - 关联知识点：{kp_titles}",
            ]
        )
        if adjusted:
            lines.append(f"  - 调整说明：**{_safe(task.get('adjustment_reason'))}**")
    return "\n".join(lines)


def format_trace(traces: list[dict[str, Any]]) -> str:
    if not traces:
        return "### Agent 执行轨迹\n\n暂无执行轨迹。"
    lines = ["### Agent 执行轨迹", ""]
    for trace in sorted(traces, key=lambda item: (str(item.get("created_at") or ""), int(item.get("id") or 0))):
        status = str(trace.get("status") or "")
        failed_marker = "【失败】 " if status == "failed" else ""
        mode_label = _execution_mode_label(str(trace.get("execution_mode") or ""))
        lines.extend(
            [
                f"- {failed_marker}`{_safe(trace.get('created_at'))}` "
                f"**{_safe(trace.get('step'))}** · {_safe(trace.get('tool_name'))} · {mode_label}",
                f"  - 状态：{_trace_status_label(status)}；耗时：{_safe(trace.get('duration_ms'))} 毫秒",
                f"  - 原因摘要：{_safe(trace.get('reason_summary'))}",
                f"  - 结果摘要：{_safe(trace.get('output_summary'))}",
            ]
        )
        provider = trace.get("provider")
        model_name = trace.get("model_name")
        if provider or model_name:
            lines.append(f"  - 模型信息：{_safe(provider)} / {_safe(model_name)}")
        fallback_reason = trace.get("fallback_reason")
        if fallback_reason:
            lines.append(f"  - 回退原因：{_safe(fallback_reason)}")
    return "\n".join(lines)


def update_session_from_plan(state: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    session = dict(state)
    session["latest_plan_data"] = data
    return session


def update_session_from_trace(state: dict[str, Any], data: list[dict[str, Any]], selected_filter: dict[str, Any]) -> dict[str, Any]:
    session = dict(state)
    session["latest_trace_data"] = data
    session["selected_trace_filter"] = selected_filter
    return session


def _format_percent(value: float) -> str:
    return f"{value * 100:.0f}%"


def _format_score(value: Any) -> str:
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return "-"


def _format_delta(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number:+.1f}"


def _format_mastery_score(value: Any) -> str:
    try:
        number = max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        number = 0.0
    return f"{number:.1f}/100"


def _task_status_label(status: str) -> str:
    return {
        "pending": "待完成",
        "completed": "已完成",
        "adjusted": "已调整",
    }.get(status, status or "-")


def _trace_status_label(status: str) -> str:
    return {
        "success": "成功",
        "failed": "失败",
    }.get(status, status or "-")


def _execution_mode_label(mode: str) -> str:
    return {
        "rule": "规则模式",
        "llm": "大模型模式",
        "fallback_rule": "模型失败后规则兜底",
    }.get(mode, mode or "-")


def _result_interpretation(correct_rate: float, weak_points: list[dict[str, Any]], adjustment_summary: str) -> str:
    if correct_rate >= 0.999 and not weak_points:
        return "**结果判断：全对，本轮不触发补救式调整。**"
    if weak_points:
        return f"**结果判断：错误较多或存在薄弱点，已触发后续任务调整。** 调整摘要：{_safe(adjustment_summary)}"
    return "**结果判断：已完成提交，暂未发现需要补救式调整的薄弱点。**"


def _safe(value: Any) -> str:
    if value is None:
        return "-"
    text = str(value)
    if contains_answer_leak(text) or "标准答案" in text:
        return "[已隐藏标准答案相关内容]"
    return text.replace("<", "&lt;").replace(">", "&gt;")
