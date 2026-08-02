from app.agent.orchestrator import _sanitize_llm_points
from app.llm.schemas import LLMContentAnalysis
from app.tools.content_parser import (
    DOMAIN_ALIASES,
    LEADING_PHRASES,
    MAX_KNOWLEDGE_POINTS,
    extract_knowledge_point_titles,
    parse_content,
)
from app.tools.exercise_generator import generate_exercises


def _raw(index: int) -> str:
    return DOMAIN_ALIASES[index][0]


def _title(index: int) -> str:
    return DOMAIN_ALIASES[index][1]


DIVIDER = "\u3001"
FULL_STOP = "\u3002"
DATA_STRUCTURE_TEXT = (
    LEADING_PHRASES[0]
    + DIVIDER.join([_raw(0), _raw(2), _raw(7), _raw(6), _raw(28), _raw(21)])
    + "\u53ca\u57fa\u7840\u5e94\u7528"
    + FULL_STOP
    + LEADING_PHRASES[3]
    + "\u7406\u89e3\u903b\u8f91\u7ed3\u6784\u4e0e\u5b58\u50a8\u7ed3\u6784\u7684\u5173\u7cfb"
    + DIVIDER.join(["", _raw(16), _raw(17), _raw(18)])
    + "\u7b49\u57fa\u672c\u64cd\u4f5c\uff0c"
    + LEADING_PHRASES[8]
    + _raw(11)
    + FULL_STOP
)


def test_data_structure_notes_extract_concise_reusable_titles() -> None:
    titles = [point.title for point in parse_content("Data structures", DATA_STRUCTURE_TEXT)]
    assert titles == [_title(index) for index in (0, 2, 7, 6, 28, 21, 16, 17, 18, 11)]


def test_leading_phrases_are_removed_and_operations_are_split_and_normalized() -> None:
    text = LEADING_PHRASES[1] + DIVIDER.join([_raw(16), _raw(17), _raw(18)]) + "\u7b49\u57fa\u672c\u64cd\u4f5c"
    text += "\uff1b" + LEADING_PHRASES[8] + _raw(11)
    assert extract_knowledge_point_titles(text) == [_title(index) for index in (16, 17, 18, 11)]


def test_fixed_terms_are_preserved_without_wrong_splitting() -> None:
    text = DIVIDER.join([_raw(2), _raw(7), _raw(6), _raw(28), _raw(21), _raw(9)])
    assert extract_knowledge_point_titles(text) == [_title(index) for index in (2, 7, 6, 28, 21, 9)]


def test_plain_linked_list_is_not_forced_to_singly_linked_list() -> None:
    assert extract_knowledge_point_titles(DIVIDER.join([_raw(20), _raw(6)])) == [_title(20), _title(6)]


def test_long_sentences_are_not_kept_as_knowledge_point_titles() -> None:
    titles = extract_knowledge_point_titles(DATA_STRUCTURE_TEXT)
    assert all(len(title) <= 20 for title in titles)
    assert all(LEADING_PHRASES[0] not in title and LEADING_PHRASES[3] not in title for title in titles)
    assert DATA_STRUCTURE_TEXT not in titles


def test_normalized_titles_are_deduplicated_in_source_order() -> None:
    text = DIVIDER.join([_raw(16), _raw(13), _raw(17), _raw(14), _raw(9), _raw(12)])
    assert extract_knowledge_point_titles(text) == [_title(index) for index in (16, 17, 11)]


def test_keeps_source_order_and_limits_to_twelve_points() -> None:
    indexes = (0, 2, 1, 7, 6, 5, 4, 28, 21, 3, 22, 25, 8, 26, 23)
    titles = extract_knowledge_point_titles(DIVIDER.join(_raw(index) for index in indexes))
    assert titles[:4] == [_title(index) for index in indexes[:4]]
    assert len(titles) == MAX_KNOWLEDGE_POINTS


def test_empty_text_uses_safe_course_based_fallback() -> None:
    points = parse_content("Discrete mathematics", "")
    assert len(points) == 3
    assert all(2 <= len(point.title) <= 20 for point in points)


def test_generic_course_uses_delimiter_based_fallback() -> None:
    titles = extract_knowledge_point_titles("Photosynthesis,Respiration;Genetics")
    assert titles == ["Photosynthesis", "Respiration", "Genetics"]


def test_learning_goal_is_combined_with_course_notes_in_source_order() -> None:
    points = parse_content(
        "Data structures",
        LEADING_PHRASES[0] + DIVIDER.join([_raw(7), _raw(28)]) + FULL_STOP,
        learning_goal="14 days " + DIVIDER.join([_raw(21), _raw(18)]),
    )
    assert [point.title for point in points] == [_title(index) for index in (7, 28, 21, 18)]


def test_llm_titles_receive_the_same_normalization_and_deduplication() -> None:
    content = LLMContentAnalysis(
        course_summary="summary",
        knowledge_points=[
            {
                "title": LEADING_PHRASES[0] + _raw(7) + DIVIDER + _raw(6),
                "description": "linear list",
                "difficulty": "basic",
                "importance": 5,
                "source_hint": "notes",
            },
            {
                "title": DIVIDER.join([_raw(16), _raw(17), _raw(18)]) + "\u7b49\u57fa\u672c\u64cd\u4f5c",
                "description": "operations",
                "difficulty": "medium",
                "importance": 4,
                "source_hint": "notes",
            },
            {
                "title": _raw(15),
                "description": "duplicate",
                "difficulty": "basic",
                "importance": 3,
                "source_hint": "notes",
            },
        ],
    )
    points = _sanitize_llm_points(content)
    assert [point.title for point in points] == [_title(index) for index in (7, 6, 16, 17, 18)]


def test_downstream_exercises_use_clean_titles_not_leading_sentences() -> None:
    points = parse_content("Data structures", DATA_STRUCTURE_TEXT)
    exercises = generate_exercises(points[:2], count=3)
    assert all(LEADING_PHRASES[0] not in exercise.question for exercise in exercises)
    assert all(LEADING_PHRASES[3] not in exercise.question for exercise in exercises)
