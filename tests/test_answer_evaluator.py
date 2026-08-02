from app.tools.answer_evaluator import evaluate_answer, normalize_answer


def test_short_answer_accepts_complexity_with_explanation() -> None:
    result = evaluate_answer(
        standard_answer="O(n)",
        user_answer="O(n)，因为需要遍历",
        question="顺序查找最坏情况下的时间复杂度是多少？",
        difficulty="basic",
        question_type="short_answer",
    )

    assert result.is_correct is True
    assert result.evaluation_reason == "用户答案包含标准答案核心内容"


def test_short_answer_normalizes_case_spaces_and_punctuation() -> None:
    assert normalize_answer("  O ( n )，遍历。 ") == "o(n),遍历."


def test_short_answer_accepts_major_sequential_search_keywords() -> None:
    result = evaluate_answer(
        standard_answer="顺序查找需要依次比较元素。",
        user_answer="它属于线性查找，需要遍历元素。",
        question="请说明顺序查找的执行特点。",
        difficulty="basic",
        question_type="short_answer",
    )

    assert result.is_correct is True
    assert result.evaluation_reason == "用户答案命中主要关键词"


def test_single_choice_does_not_use_short_answer_containment() -> None:
    result = evaluate_answer(
        standard_answer="B",
        user_answer="B 不是我的选择，我选择 A",
        question="以下哪项描述正确？\nA. 选项甲\nB. 选项乙",
        difficulty="basic",
        question_type="single_choice",
    )

    assert result.is_correct is False


def test_code_question_does_not_use_short_answer_containment() -> None:
    result = evaluate_answer(
        standard_answer="malloc(sizeof(Node))",
        user_answer="这里不应该使用malloc(sizeof(Node))",
        question="代码补全：Node *p = ______;",
        difficulty="basic",
        question_type="short_answer",
    )

    assert result.is_correct is False
