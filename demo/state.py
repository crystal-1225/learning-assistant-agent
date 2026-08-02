from dataclasses import dataclass, field
from typing import Any


@dataclass
class DemoSessionState:
    user_id: int | None = None
    course_id: int | None = None
    plan_id: int | None = None
    task_id: int | None = None
    exercises: list[dict[str, Any]] = field(default_factory=list)

