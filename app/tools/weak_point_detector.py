from dataclasses import dataclass

from app.tools.progress_evaluator import MasteryUpdate


@dataclass(frozen=True)
class WeakKnowledgePoint:
    id: int
    title: str
    mastery_score: float
    current_correct_rate: float
    reason: str


def detect_weak_points(updates: list[MasteryUpdate]) -> list[WeakKnowledgePoint]:
    weak_points: list[WeakKnowledgePoint] = []
    for update in updates:
        reason = _weak_reason(update)
        if reason:
            weak_points.append(
                WeakKnowledgePoint(
                    id=update.knowledge_point_id,
                    title=update.knowledge_point_title,
                    mastery_score=update.new_score,
                    current_correct_rate=update.current_correct_rate,
                    reason=reason,
                )
            )
    return weak_points


def _weak_reason(update: MasteryUpdate) -> str | None:
    if update.current_correct_rate < 0.6:
        return "本次正确率低于60%，需要补救复习"
    if update.current_correct_rate < 0.8 and update.new_score < 60:
        return "本次正确率处于60%-80%且累计掌握度低于60，需要巩固"
    return None
