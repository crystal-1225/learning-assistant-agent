from datetime import date

from app.tools.types import GoalSummary


def analyze_goal(goal: str, start_date: date, end_date: date, daily_minutes: int) -> GoalSummary:
    total_days = (end_date - start_date).days + 1
    summary = f"在 {total_days} 天内，每天学习 {daily_minutes} 分钟，目标是：{goal.strip()}"
    return GoalSummary(
        goal=goal.strip(),
        start_date=start_date,
        end_date=end_date,
        daily_minutes=daily_minutes,
        total_days=total_days,
        summary=summary,
    )

