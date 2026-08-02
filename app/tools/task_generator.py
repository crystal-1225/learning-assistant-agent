from app.tools.types import DayPlanDraft


def generate_tasks(day_plans: list[DayPlanDraft]) -> list[DayPlanDraft]:
    if not day_plans:
        raise ValueError("day_plans cannot be empty")
    return day_plans

