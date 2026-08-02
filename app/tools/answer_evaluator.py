import re
import string
import unicodedata
from dataclasses import dataclass


PUNCTUATION_MAP = str.maketrans(
    {
        "，": ",",
        "。": ".",
        "！": "!",
        "？": "?",
        "；": ";",
        "：": ":",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "、": ",",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
    }
)
COMPLEXITY_PATTERN = re.compile(r"\bo\s*\(\s*[^)]+\s*\)", re.IGNORECASE)
CODE_QUESTION_MARKERS = ("```", "______", "____", "代码补全", "找 bug", "找bug", "代码阅读")
CHOICE_QUESTION_MARKERS = ("以下哪项", "以下哪个", "选择题", "判断题", "a.", "a。", "a、")


@dataclass(frozen=True)
class EvaluationResult:
    is_correct: bool
    normalized_user_answer: str
    normalized_standard_answer: str
    evaluation_reason: str


def evaluate_answer(
    standard_answer: str,
    user_answer: str,
    question: str,
    difficulty: str,
    question_type: str | None = None,
) -> EvaluationResult:
    normalized_user = normalize_answer(user_answer)
    normalized_standard = normalize_answer(standard_answer)

    if _numeric_equal(normalized_user, normalized_standard):
        return EvaluationResult(True, normalized_user, normalized_standard, "数字标准化后答案一致")

    if normalized_user == normalized_standard:
        return EvaluationResult(True, normalized_user, normalized_standard, "标准化后答案一致")

    standard_tokens = _important_tokens(normalized_standard)
    user_tokens = _important_tokens(normalized_user)
    if standard_tokens and standard_tokens.issubset(user_tokens):
        return EvaluationResult(True, normalized_user, normalized_standard, "用户答案覆盖标准答案关键词")

    if _uses_short_answer_matching(question, question_type):
        if _standard_answer_is_contained(normalized_standard, normalized_user):
            return EvaluationResult(True, normalized_user, normalized_standard, "用户答案包含标准答案核心内容")
        if _major_keyword_match(normalized_standard, normalized_user, question):
            return EvaluationResult(True, normalized_user, normalized_standard, "用户答案命中主要关键词")

    return EvaluationResult(False, normalized_user, normalized_standard, "标准化或关键词匹配后仍不一致")


def normalize_answer(answer: str) -> str:
    normalized = unicodedata.normalize("NFKC", answer).strip().lower().translate(PUNCTUATION_MAP)
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"\s*([,.!?;:()\[\]])\s*", r"\1", normalized)
    return normalized.strip()


def _numeric_equal(left: str, right: str) -> bool:
    try:
        return float(left) == float(right)
    except ValueError:
        return False


def _important_tokens(answer: str) -> set[str]:
    cleaned = answer.translate(str.maketrans("", "", string.punctuation))
    return {token for token in re.split(r"\s+", cleaned) if len(token) >= 2}


def _uses_short_answer_matching(question: str, question_type: str | None) -> bool:
    normalized_question = normalize_answer(question)
    if any(marker in normalized_question for marker in CODE_QUESTION_MARKERS):
        return False
    if question_type is not None:
        return question_type == "short_answer"
    return not any(marker in normalized_question for marker in CHOICE_QUESTION_MARKERS)


def _standard_answer_is_contained(standard_answer: str, user_answer: str) -> bool:
    standard = standard_answer.rstrip(".,!?;:")
    return len(standard) >= 2 and standard in user_answer


def _major_keyword_match(standard_answer: str, user_answer: str, question: str) -> bool:
    standard_complexities = {_normalize_complexity(item) for item in COMPLEXITY_PATTERN.findall(standard_answer)}
    user_complexities = {_normalize_complexity(item) for item in COMPLEXITY_PATTERN.findall(user_answer)}
    if standard_complexities & user_complexities:
        return True

    context = normalize_answer(f"{question} {standard_answer}")
    if "顺序查找" not in context and "线性查找" not in context:
        return False

    keywords = ("o(n)", "线性", "遍历", "逐个", "依次比较")
    matched = {keyword for keyword in keywords if keyword in user_answer}
    asks_complexity = any(keyword in normalize_answer(question) for keyword in ("复杂度", "最坏", "平均"))
    return bool(matched) if asks_complexity else len(matched) >= 2


def _normalize_complexity(value: str) -> str:
    return re.sub(r"\s+", "", value.lower())
