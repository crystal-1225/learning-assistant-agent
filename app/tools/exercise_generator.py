import re

from app.tools.types import ExerciseDraft, KnowledgePointDraft


SUPPORTED_QUESTION_TYPES = {"single_choice", "short_answer"}
CODE_TERMS = ("c语言", "指针", "结构体", "malloc", "free")


def normalize_question(question: str) -> str:
    """Return a deterministic key that ignores whitespace and trailing punctuation."""
    normalized = re.sub(r"\s+", "", question.strip().lower())
    return normalized.rstrip(".,!?;:，。！？；：、")


def exercise_format(draft: ExerciseDraft) -> str:
    """Classify persisted question text into the V3 learning format."""
    question = normalize_question(draft.question)
    if "```" in draft.question or "______" in draft.question or "____" in draft.question or "代码补全" in question:
        return "code"
    if draft.question_type == "single_choice" and ("判断题" in question or "正确还是错误" in question):
        return "true_false"
    if draft.question_type == "single_choice":
        return "single_choice"
    return "short_answer"


def difficulty_for_day(day_number: int) -> str:
    """Keep early learning basic and advance only after foundational days."""
    return "basic" if day_number <= 3 else "medium"


def ensure_unique_exercises(
    exercises: list[ExerciseDraft],
    knowledge_points: list[KnowledgePointDraft],
    *,
    count: int,
    expected_difficulty: str | None = None,
    code_context: bool | None = None,
) -> list[ExerciseDraft]:
    """Validate rule and LLM exercises with one shared V3 contract."""
    unique: list[ExerciseDraft] = []
    seen_questions: set[str] = set()
    seen_semantics: set[tuple[str, str, str]] = set()
    for draft in exercises:
        if draft.knowledge_point_index < 0 or draft.knowledge_point_index >= len(knowledge_points):
            raise ValueError("exercise knowledge point index is invalid")
        if draft.question_type not in SUPPORTED_QUESTION_TYPES:
            raise ValueError("exercise question type is invalid")
        if expected_difficulty is not None and draft.difficulty != expected_difficulty:
            raise ValueError("exercise difficulty does not match learning day")
        question_key = normalize_question(draft.question)
        if not question_key:
            raise ValueError("exercise question cannot be blank")
        point_key = normalize_question(knowledge_points[draft.knowledge_point_index].title)
        format_key = exercise_format(draft)
        template_key = question_key.replace(point_key, "{knowledge_point}") if point_key else question_key
        semantic_key = (point_key, format_key, template_key)
        if question_key in seen_questions or semantic_key in seen_semantics:
            continue
        seen_questions.add(question_key)
        seen_semantics.add(semantic_key)
        unique.append(draft)

    if len(unique) != count:
        raise ValueError("exercise set must contain the requested number of distinct questions")

    available_points = len(_unique_knowledge_points(knowledge_points))
    used_points = {item.knowledge_point_index for item in unique}
    if len(used_points) < min(count, available_points):
        raise ValueError("exercise set must cover different available knowledge points")

    should_use_code = has_code_context(knowledge_points) if code_context is None else code_context
    expected_formats = ("short_answer", "single_choice", "code" if should_use_code else "true_false")
    if count == 3 and tuple(exercise_format(item) for item in unique) != expected_formats:
        raise ValueError("exercise set must use the required diverse learning formats")
    return unique


def generate_exercises(
    knowledge_points: list[KnowledgePointDraft],
    count: int = 3,
    *,
    day_number: int = 1,
    course_title: str = "",
    code_context: bool | None = None,
) -> list[ExerciseDraft]:
    if not knowledge_points:
        raise ValueError("knowledge_points cannot be empty")
    if count < 0:
        raise ValueError("count cannot be negative")
    if count == 0:
        return []
    if count != 3:
        raise ValueError("Exercise Generator V3 currently generates exactly three exercises")

    points = _unique_knowledge_points(knowledge_points)
    expected_difficulty = difficulty_for_day(day_number)
    uses_code = has_code_context(knowledge_points, course_title) if code_context is None else code_context
    formats = ("short_answer", "single_choice", "code" if uses_code else "true_false")
    drafts: list[ExerciseDraft] = []
    for position, question_format in enumerate(formats):
        source_index, point = _select_point(points, question_format, position)
        drafts.append(
            _build_draft(
                point=point,
                knowledge_point_index=source_index,
                question_format=question_format,
                difficulty=expected_difficulty,
            )
        )
    return ensure_unique_exercises(
        drafts,
        knowledge_points,
        count=count,
        expected_difficulty=expected_difficulty,
        code_context=uses_code,
    )


def _unique_knowledge_points(knowledge_points: list[KnowledgePointDraft]) -> list[tuple[int, KnowledgePointDraft]]:
    unique: list[tuple[int, KnowledgePointDraft]] = []
    seen_titles: set[str] = set()
    for index, point in enumerate(knowledge_points):
        title_key = normalize_question(point.title)
        if not title_key or title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        unique.append((index, point))
    if not unique:
        raise ValueError("knowledge_points must contain a title")
    return unique


def _select_point(
    points: list[tuple[int, KnowledgePointDraft]],
    question_format: str,
    position: int,
) -> tuple[int, KnowledgePointDraft]:
    if question_format == "code":
        for source_index, point in points:
            if _is_code_point(point.title):
                return source_index, point
    return points[position % len(points)]


def _build_draft(
    *,
    point: KnowledgePointDraft,
    knowledge_point_index: int,
    question_format: str,
    difficulty: str,
) -> ExerciseDraft:
    title = point.title
    if question_format == "short_answer":
        question, answer, explanation = _short_answer_template(title)
        question_type = "short_answer"
    elif question_format == "single_choice":
        question, answer, explanation = _single_choice_template(title)
        question_type = "single_choice"
    elif question_format == "true_false":
        question, answer, explanation = _true_false_template(title)
        question_type = "single_choice"
    else:
        question, answer, explanation = _code_template(title)
        question_type = "short_answer"
    return ExerciseDraft(
        knowledge_point_index=knowledge_point_index,
        question=question,
        standard_answer=answer,
        explanation=explanation,
        difficulty=difficulty,
        question_type=question_type,
    )


def _short_answer_template(title: str) -> tuple[str, str, str]:
    family = _topic_family(title)
    if family == "time_complexity":
        return (
            "顺序查找在最坏情况下的时间复杂度是多少？请说明原因。",
            "O(n)。最坏情况下需要依次比较全部 n 个元素。",
            "考查顺序查找的最坏情况分析。",
        )
    if family == "sequential_list":
        return (
            "请写出顺序表在指定位置插入元素时的两个主要步骤。",
            "先将插入位置及之后的元素依次后移，再在目标位置写入新元素并更新长度。",
            "考查顺序表插入的移动与长度更新。",
        )
    if family == "linked_list":
        return (
            "删除单链表中指定结点时，需要先找到哪个前驱结点？为什么？",
            "需要找到待删除结点的前驱结点，以便将前驱结点的 next 指向待删除结点的后继。",
            "考查单链表删除中的指针连接关系。",
        )
    if family == "stack":
        return (
            "请说明栈的基本存取特征，并列出入栈和出栈各自操作的一端。",
            "栈遵循后进先出；入栈和出栈都在栈顶进行。",
            "考查栈的 LIFO 特征和栈顶操作位置。",
        )
    if family == "queue":
        return (
            "请说明队列的入队和出队分别发生在什么位置。",
            "入队在队尾进行，出队在队头进行。",
            "考查队列的 FIFO 特征。",
        )
    return (
        f"请简述“{title}”的核心含义，并说明一个学习时需要关注的要点。",
        f"答案应说明“{title}”的核心含义，并给出一个关键性质、操作或适用场景。",
        f"考查对“{title}”的基础概念理解。",
    )


def _single_choice_template(title: str) -> tuple[str, str, str]:
    family = _topic_family(title)
    if family == "data_structure":
        return (
            "以下哪项属于数据结构的逻辑结构？\nA. 顺序存储\nB. 链式存储\nC. 线性结构\nD. 动态分配",
            "C。线性结构描述元素之间的逻辑关系。",
            "考查逻辑结构与存储结构的区分。",
        )
    if family == "time_complexity":
        return (
            "下列哪种操作在元素逐个检查时的时间复杂度通常为 O(n)？\nA. 顺序查找\nB. 访问数组首元素\nC. 栈顶取值\nD. 队尾入队",
            "A。顺序查找最坏情况下需要检查全部元素。",
            "考查 O(n) 的典型操作。",
        )
    if family == "sequential_list":
        return (
            "顺序表插入一个元素时，平均需要移动的元素数量最接近下列哪项？\nA. 0\nB. 1\nC. n/2\nD. n²",
            "C。平均插入位置在中间附近，约需移动 n/2 个元素。",
            "考查顺序表插入的平均移动代价。",
        )
    if family == "linked_list":
        return (
            "删除单链表中 p 所指结点的后继结点时，关键指针操作是？\nA. p = p->next\nB. p->next = p->next->next\nC. p = NULL\nD. head = NULL",
            "B。应让 p 直接连接到原后继结点的下一个结点。",
            "考查单链表删除结点时的指针修改。",
        )
    if family == "stack":
        return (
            "栈属于哪种存取方式？\nA. FIFO\nB. LIFO\nC. 双向访问\nD. 哈希访问",
            "B。栈遵循后进先出（LIFO）。",
            "考查栈的基本存取规则。",
        )
    if family == "queue":
        return (
            "队列属于哪种存取方式？\nA. FIFO\nB. LIFO\nC. 随机访问\nD. 哈希访问",
            "A。队列遵循先进先出（FIFO）。",
            "考查队列的基本存取规则。",
        )
    return (
        f"关于“{title}”，以下哪项更符合学习时应关注的内容？\nA. 只记住名称\nB. 理解核心含义、适用场景和关键操作\nC. 忽略边界条件\nD. 只背诵结论",
        "B。应理解核心含义、适用场景和关键操作。",
        f"考查学习“{title}”时的关键关注点。",
    )


def _true_false_template(title: str) -> tuple[str, str, str]:
    family = _topic_family(title)
    statements = {
        "time_complexity": "顺序查找在最坏情况下需要检查全部元素，因此时间复杂度为 O(n)。",
        "sequential_list": "顺序表可以通过下标直接访问元素。",
        "linked_list": "单链表中访问第 i 个结点通常需要从头结点开始逐个遍历。",
        "stack": "栈的入栈和出栈操作都在栈顶进行。",
        "queue": "队列的入队在队尾、出队在队头进行。",
    }
    statement = statements.get(family, f"“{title}”的学习应同时关注核心含义、适用场景和边界条件。")
    return (
        f"判断题：{statement}\nA. 正确\nB. 错误",
        "A。该表述正确。",
        f"考查“{title}”的基础判断。",
    )


def _code_template(title: str) -> tuple[str, str, str]:
    family = _topic_family(title)
    if family == "linked_list":
        return (
            "代码补全：下面语句用于让 p 指向单链表的首元结点，请填写空白。\n```c\nNode *p = ________;\n```",
            "head",
            "考查单链表首指针及 C 语言指针赋值。",
        )
    if family == "sequential_list":
        return (
            "代码补全：顺序表尾部插入元素时，填写赋值语句中的空白。\n```c\nL.data[L.length] = ________;\nL.length++;\n```",
            "value",
            "考查顺序表存储数组与长度维护。",
        )
    return (
        "代码补全：为链表结点分配内存后，申请失败时应返回什么？\n```c\nNode *p = (Node *)malloc(sizeof(Node));\nif (p == NULL) return ________;\n```",
        "NULL",
        f"考查“{title}”相关的 C 语言内存申请与空指针处理。",
    )


def _topic_family(title: str) -> str:
    value = normalize_question(title)
    if "时间复杂度" in value or "空间复杂度" in value:
        return "time_complexity"
    if "顺序表" in value:
        return "sequential_list"
    if "链表" in value:
        return "linked_list"
    if "栈" in value:
        return "stack"
    if "队列" in value:
        return "queue"
    if "数据结构" in value:
        return "data_structure"
    return "generic"


def _is_code_point(title: str) -> bool:
    value = normalize_question(title)
    return any(term in value for term in CODE_TERMS)


def has_code_context(knowledge_points: list[KnowledgePointDraft], course_title: str = "") -> bool:
    return any(_is_code_point(point.title) for point in knowledge_points) or _is_code_point(course_title)
