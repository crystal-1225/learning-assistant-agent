import pytest

from app.tools.exercise_generator import (
    difficulty_for_day,
    ensure_unique_exercises,
    exercise_format,
    generate_exercises,
    normalize_question,
)
from app.tools.types import ExerciseDraft, KnowledgePointDraft


def point(title: str) -> KnowledgePointDraft:
    return KnowledgePointDraft(title=title, description=f"{title} 的说明", difficulty="basic")


def test_generates_three_unique_questions_with_diverse_targets() -> None:
    exercises = generate_exercises([point("数据结构基本概念"), point("时间复杂度")], count=3)

    assert len(exercises) == 3
    assert len({normalize_question(item.question) for item in exercises}) == 3
    assert [item.knowledge_point_index for item in exercises] == [0, 1, 0]
    assert {item.question_type for item in exercises} == {"short_answer", "single_choice"}
    assert [exercise_format(item) for item in exercises] == ["short_answer", "single_choice", "true_false"]


def test_same_knowledge_point_input_still_generates_distinct_questions() -> None:
    exercises = generate_exercises([point("顺序表"), point(" 顺序表 ")], count=3)

    assert len(exercises) == 3
    assert len({normalize_question(item.question) for item in exercises}) == 3
    assert {item.knowledge_point_index for item in exercises} == {0}


def test_question_normalization_detects_whitespace_and_punctuation_variants() -> None:
    assert normalize_question(" 请 解释 顺序表 ？ ") == normalize_question("请解释顺序表。")
    assert normalize_question("WHAT IS A STACK!!!") == normalize_question("what is a stack")


def test_duplicate_external_questions_are_rejected_after_normalization() -> None:
    points = [point("栈")]
    drafts = [
        ExerciseDraft(0, "请解释栈？", "答案一", "说明一", "basic", "short_answer"),
        ExerciseDraft(0, " 请 解释 栈。 ", "答案二", "说明二", "basic", "short_answer"),
        ExerciseDraft(0, "请写出栈的一项应用。", "答案三", "说明三", "basic", "short_answer"),
    ]

    with pytest.raises(ValueError, match="distinct questions"):
        ensure_unique_exercises(drafts, points, count=3)


def test_one_knowledge_point_uses_backup_templates_without_repeating() -> None:
    exercises = generate_exercises([point("队列")], count=3)

    assert len(exercises) == 3
    assert len({normalize_question(item.question) for item in exercises}) == 3
    assert all(item.knowledge_point_index == 0 for item in exercises)
    assert all("答案应" not in item.question for item in exercises)
    assert all("prompt" not in item.question.lower() for item in exercises)


def test_data_structure_topics_use_specialized_templates() -> None:
    exercises = generate_exercises([point("时间复杂度"), point("栈")], count=3)

    assert "顺序查找" in exercises[0].question
    assert "栈属于哪种存取方式" in exercises[1].question
    assert "判断题" in exercises[2].question


def test_generic_course_uses_a_different_template_family() -> None:
    data_structure = generate_exercises([point("时间复杂度"), point("栈")], count=3)
    generic = generate_exercises([point("函数极限"), point("导数")], count=3)

    assert "顺序查找" in data_structure[0].question
    assert "顺序查找" not in generic[0].question
    assert "函数极限" in generic[0].question


def test_c_language_course_generates_code_completion_as_third_question() -> None:
    exercises = generate_exercises(
        [point("数据结构基本概念"), point("顺序表")],
        count=3,
        course_title="数据结构（C语言版）",
    )

    assert [exercise_format(item) for item in exercises] == ["short_answer", "single_choice", "code"]
    assert "```c" in exercises[2].question
    assert exercises[2].question_type == "short_answer"


def test_day_based_difficulty_progression_is_deterministic() -> None:
    assert difficulty_for_day(1) == "basic"
    assert difficulty_for_day(3) == "basic"
    assert difficulty_for_day(4) == "medium"
    exercises = generate_exercises([point("顺序表"), point("栈")], count=3, day_number=4)
    assert {item.difficulty for item in exercises} == {"medium"}


def test_shared_validator_rejects_llm_style_uniform_formats_and_wrong_difficulty() -> None:
    points = [point("顺序表"), point("栈")]
    drafts = [
        ExerciseDraft(0, "请解释顺序表。", "a", "e", "basic", "short_answer"),
        ExerciseDraft(1, "请说明栈。", "a", "e", "basic", "short_answer"),
        ExerciseDraft(0, "请描述顺序表。", "a", "e", "basic", "short_answer"),
    ]
    with pytest.raises(ValueError, match="diverse learning formats"):
        ensure_unique_exercises(drafts, points, count=3, expected_difficulty="basic", code_context=False)

    valid = generate_exercises(points, count=3, day_number=4)
    with pytest.raises(ValueError, match="difficulty"):
        ensure_unique_exercises(valid, points, count=3, expected_difficulty="basic", code_context=False)
