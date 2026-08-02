from datetime import timedelta

from app.tools.types import DayPlanDraft, GoalSummary, KnowledgePointDraft


def generate_plan(goal_summary: GoalSummary, knowledge_points: list[KnowledgePointDraft]) -> list[DayPlanDraft]:
    if not knowledge_points:
        raise ValueError("knowledge_points cannot be empty")

    day_plans: list[DayPlanDraft] = []
    for day_index in range(goal_summary.total_days):
        task_date = goal_summary.start_date + timedelta(days=day_index)
        kp_index = day_index % len(knowledge_points)
        next_index = (kp_index + 1) % len(knowledge_points)
        indexes = [kp_index] if len(knowledge_points) == 1 else [kp_index, next_index]
        titles = "、".join(knowledge_points[index].title for index in indexes)
        day_plans.append(
            DayPlanDraft(
                task_date=task_date,
                title=f"第 {day_index + 1} 天：学习 {titles}",
                content=(
                    f"用 {goal_summary.daily_minutes} 分钟完成知识点梳理、例题理解和自测记录。"
                    f"今日重点：{titles}。"
                ),
                knowledge_point_indexes=indexes,
            )
        )
    return day_plans

