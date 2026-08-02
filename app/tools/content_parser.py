import re
from collections.abc import Iterable

from app.tools.types import KnowledgePointDraft


MAX_KNOWLEDGE_POINTS = 12
MAX_TITLE_LENGTH = 20
MIN_GENERIC_TITLE_LENGTH = 2
MIN_DOMAIN_COVERAGE = 4

# The glossary improves common data-structure notes but is only one source of
# candidates. Generic courses continue through the delimiter-based fallback.
DOMAIN_ALIASES: tuple[tuple[str, str], ...] = (
    ("数据结构基本概念", "数据结构基本概念"),
    ("空间复杂度", "空间复杂度"),
    ("时间复杂度", "时间复杂度"),
    ("循环队列", "循环队列"),
    ("循环链表", "循环链表"),
    ("双链表", "双链表"),
    ("单链表", "单链表"),
    ("顺序表", "顺序表"),
    ("二叉树", "二叉树"),
    ("C语言代码实现", "C语言实现"),
    ("使用C语言完成实现", "C语言实现"),
    ("C语言完成核心代码实现", "C语言实现"),
    ("C语言", "C语言实现"),
    ("插入操作", "插入操作"),
    ("删除操作", "删除操作"),
    ("查找操作", "查找操作"),
    ("插入", "插入操作"),
    ("删除", "删除操作"),
    ("查找", "查找操作"),
    ("数据结构", "数据结构"),
    ("链表", "链表"),
    ("队列", "队列"),
    ("数组", "数组"),
    ("排序", "排序"),
    ("二叉树", "二叉树"),
    ("树", "树"),
    ("图", "图"),
    ("串", "串"),
    ("栈", "栈"),
)

LEADING_PHRASES = (
    "课程内容包括",
    "主要内容包括",
    "学习内容包括",
    "学习重点为",
    "重点掌握",
    "需要理解",
    "需要掌握",
    "能够使用",
    "并能够",
    "掌握",
    "理解",
    "使用",
)
TRAILING_PATTERNS = (
    r"(?:等内容|等基本操作|相关知识|基础应用|核心代码实现)$",
    r"等$",
)
NON_TOPIC_PATTERNS = (
    r"(?:的)?关系$",
    r"^(?:课程|学习|知识点|内容|重点|基础)$",
    r"^(?:准备|完成|能够|独立)",
)


def parse_content(
    course_title: str,
    material_text: str,
    *,
    learning_goal: str = "",
) -> list[KnowledgePointDraft]:
    """Extract concise, reusable knowledge-point drafts without NLP dependencies."""
    source_text = "\n".join(part.strip() for part in (material_text, learning_goal) if part and part.strip())
    titles = extract_knowledge_point_titles(source_text)
    if not titles:
        return _default_points(course_title)
    return [
        KnowledgePointDraft(
            title=title,
            description=f"从课程资料中提取：{title}",
            difficulty="basic" if index < 4 else "medium",
        )
        for index, title in enumerate(titles)
    ]


def extract_knowledge_point_titles(text: str, *, limit: int = MAX_KNOWLEDGE_POINTS) -> list[str]:
    """Return normalized titles in source order for rules and LLM output alike."""
    if limit <= 0 or not text or not text.strip():
        return []

    domain_titles = _extract_domain_titles(text)
    generic_titles = _extract_generic_titles(text) if len(_deduplicate_and_prune(domain_titles, limit=limit)) < MIN_DOMAIN_COVERAGE else []
    return _deduplicate_and_prune([*domain_titles, *generic_titles], limit=limit)


def normalize_knowledge_point_title(title: str, *, limit: int = MAX_KNOWLEDGE_POINTS) -> list[str]:
    """Normalize one externally supplied title, including accidental long sentences."""
    return extract_knowledge_point_titles(title, limit=limit)


def _extract_domain_titles(text: str) -> list[str]:
    matches: list[tuple[int, int, str]] = []
    for alias, normalized in DOMAIN_ALIASES:
        for match in re.finditer(re.escape(alias), text, flags=re.IGNORECASE):
            matches.append((match.start(), -(match.end() - match.start()), normalized))
    matches.sort()

    titles: list[str] = []
    occupied: list[tuple[int, int]] = []
    for start, negative_length, normalized in matches:
        end = start - negative_length
        if any(start >= left and end <= right for left, right in occupied):
            continue
        occupied.append((start, end))
        titles.append(normalized)
    return titles


def _extract_generic_titles(text: str) -> list[str]:
    fragments = re.split(r"[\n\r。；;：:、，,]+|(?:以及|及|和|与)", text)
    titles: list[str] = []
    for fragment in fragments:
        cleaned = _clean_fragment(fragment)
        if _is_meaningful_generic_title(cleaned):
            titles.append(_standardize_common_term(cleaned))
    return titles


def _clean_fragment(fragment: str) -> str:
    value = re.sub(r"\s+", "", fragment)
    value = re.sub(r"^(?:在)?\d+天内(?:系统)?(?:掌握|学习)?", "", value)
    value = re.sub(r"^\d+天(?:内)?(?:复习|学习)", "", value)
    value = value.strip("　\t0123456789.()（）[]【】")
    changed = True
    while value and changed:
        changed = False
        for phrase in LEADING_PHRASES:
            if value.startswith(phrase):
                value = value[len(phrase) :].lstrip("：:，,、")
                changed = True
    for pattern in TRAILING_PATTERNS:
        value = re.sub(pattern, "", value)
    return value.strip("：:，,、。；; ")


def _standardize_common_term(value: str) -> str:
    exact = {
        "插入": "插入操作",
        "删除": "删除操作",
        "查找": "查找操作",
        "C语言代码实现": "C语言实现",
        "C语言": "C语言实现",
        "使用C语言完成实现": "C语言实现",
        "使用C语言完成核心代码实现": "C语言实现",
    }
    return exact.get(value, value)


def _is_meaningful_generic_title(value: str) -> bool:
    if len(value) < MIN_GENERIC_TITLE_LENGTH or len(value) > MAX_TITLE_LENGTH:
        return False
    return not any(re.search(pattern, value) for pattern in NON_TOPIC_PATTERNS)


def _deduplicate_and_prune(items: Iterable[str], *, limit: int) -> list[str]:
    titles: list[str] = []
    keys: list[str] = []
    for item in items:
        value = _standardize_common_term(_clean_fragment(item))
        if not value or len(value) > MAX_TITLE_LENGTH:
            continue
        if len(value) < MIN_GENERIC_TITLE_LENGTH and value not in {"栈", "树", "图", "串"}:
            continue
        key = _title_key(value)
        if not key or key in keys:
            continue
        # A generic sentence that contains an already retained concise topic is
        # less useful for planning and should not be persisted as a second point.
        if any(existing in key and len(key) - len(existing) >= 6 for existing in keys):
            continue
        replacement_index = next(
            (index for index, existing in enumerate(keys) if key in existing and len(existing) - len(key) >= 6),
            None,
        )
        if replacement_index is not None:
            titles[replacement_index] = value
            keys[replacement_index] = key
            continue
        titles.append(value)
        keys.append(key)
        if len(titles) == limit:
            break
    return titles


def _title_key(value: str) -> str:
    return re.sub(r"[\s\W_]+", "", value, flags=re.UNICODE).lower()


def _default_points(course_title: str) -> list[KnowledgePointDraft]:
    base = re.sub(r"\s+", "", course_title).strip()[:12] or "课程"
    titles = [f"{base}核心概念", f"{base}基础方法", f"{base}典型练习"]
    return [
        KnowledgePointDraft(
            title=title[:MAX_TITLE_LENGTH],
            description=f"根据课程名称生成的默认知识点：{title[:MAX_TITLE_LENGTH]}",
            difficulty="basic",
        )
        for title in titles
    ]
