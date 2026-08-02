from dataclasses import dataclass

from app.models.entities import DailyTask, DailyTaskKnowledgePoint, TaskStatus
from app.tools.weak_point_detector import WeakKnowledgePoint


@dataclass(frozen=True)
class ReplanResult:
    adjustment_summary: str
    adjusted_task_ids: list[int]


def adjust_future_tasks(
    *,
    current_task: DailyTask,
    future_tasks: list[DailyTask],
    weak_knowledge_points: list[WeakKnowledgePoint],
    notes: str | None,
) -> ReplanResult:
    if not weak_knowledge_points:
        return ReplanResult("未发现明显薄弱知识点，后续计划保持不变", [])

    adjustable = [
        task
        for task in sorted(future_tasks, key=lambda item: item.task_date)
        if task.task_date > current_task.task_date and task.status != TaskStatus.COMPLETED.value
    ]
    if not adjustable:
        return ReplanResult("发现薄弱知识点，但暂无可调整的后续未完成任务", [])

    target_task = adjustable[0]
    existing_ids = {link.knowledge_point_id for link in target_task.knowledge_point_links}
    added_points: list[WeakKnowledgePoint] = []
    for weak_point in weak_knowledge_points:
        if weak_point.id not in existing_ids:
            target_task.knowledge_point_links.append(
                DailyTaskKnowledgePoint(daily_task_id=target_task.id, knowledge_point_id=weak_point.id)
            )
            existing_ids.add(weak_point.id)
            added_points.append(weak_point)

    if not added_points:
        return ReplanResult("最近的后续任务已包含本次薄弱知识点，无需重复调整", [])

    added_titles = [point.title for point in added_points]
    trigger_details = "；".join(f"{point.title}（{point.reason}）" for point in added_points)
    adjustment_content = "新增基础补救练习，并建议额外学习10分钟"
    addition = (
        "\n调整：优先复习薄弱知识点："
        + "、".join(added_titles)
        + f"。触发依据：{trigger_details}。调整内容：{adjustment_content}。"
    )
    if notes:
        addition += f" 用户备注摘要：{notes[:80]}"
    target_task.content += addition
    target_task.adjustment_reason = (
        f"薄弱知识点：{'、'.join(added_titles)}；触发依据：{trigger_details}；调整内容：{adjustment_content}"
    )
    target_task.status = TaskStatus.ADJUSTED.value

    return ReplanResult(
        adjustment_summary=f"已调整任务“{target_task.title}”：{'、'.join(added_titles)}，{adjustment_content}",
        adjusted_task_ids=[target_task.id],
    )
