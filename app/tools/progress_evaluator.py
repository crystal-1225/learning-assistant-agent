from dataclasses import dataclass


@dataclass(frozen=True)
class KnowledgePointPerformance:
    knowledge_point_id: int
    knowledge_point_title: str
    old_score: float
    previous_confidence: float
    correct_count: int
    total_count: int


@dataclass(frozen=True)
class MasteryUpdate:
    knowledge_point_id: int
    knowledge_point_title: str
    old_score: float
    new_score: float
    score_change: float
    correct_count: int
    total_count: int
    confidence: float
    change_reason: str
    current_correct_rate: float


def evaluate_progress(
    performances: list[KnowledgePointPerformance],
    *,
    self_rating: int,
    completed: bool,
) -> list[MasteryUpdate]:
    updates: list[MasteryUpdate] = []
    for performance in performances:
        if performance.total_count == 0:
            continue
        correct_rate = performance.correct_count / performance.total_count
        new_score = calculate_new_score(
            old_score=performance.old_score,
            correct_rate=correct_rate,
            self_rating=self_rating,
            completed=completed,
        )
        confidence = min(1.0, round(performance.previous_confidence + performance.total_count * 0.1, 2))
        updates.append(
            MasteryUpdate(
                knowledge_point_id=performance.knowledge_point_id,
                knowledge_point_title=performance.knowledge_point_title,
                old_score=round(performance.old_score, 2),
                new_score=new_score,
                score_change=round(new_score - performance.old_score, 2),
                correct_count=performance.correct_count,
                total_count=performance.total_count,
                confidence=confidence,
                change_reason=(
                    f"本知识点答对{performance.correct_count}/{performance.total_count}，"
                    f"自评{self_rating}/5，任务{'已完成' if completed else '未完成'}"
                ),
                current_correct_rate=round(correct_rate, 2),
            )
        )
    return updates


def calculate_new_score(*, old_score: float, correct_rate: float, self_rating: int, completed: bool) -> float:
    # 掌握度公式：
    # task_performance = correct_rate * 70 + ((self_rating - 1) / 4) * 20 + completion_bonus
    # new_score = old_score * 0.6 + task_performance * 0.4，最后限制在 0 到 100。
    self_rating_normalized = (self_rating - 1) / 4
    completion_bonus = 10 if completed else 0
    task_performance = correct_rate * 70 + self_rating_normalized * 20 + completion_bonus
    return round(min(100, max(0, old_score * 0.6 + task_performance * 0.4)), 2)

