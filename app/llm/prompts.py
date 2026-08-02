def goal_prompt(*, goal: str, start_date: str, end_date: str, daily_minutes: int) -> str:
    return (
        "请将学习目标整理为 JSON。不要修改日期和每日学习分钟数。"
        f"\n目标：{goal}\n开始日期：{start_date}\n结束日期：{end_date}\n每日分钟数：{daily_minutes}"
    )


def content_prompt(*, course_title: str, material_text: str, learning_goal: str = "") -> str:
    return (
        "请从课程资料中提取最多8个简洁、可复用的知识点，返回 JSON。"
        "知识点名称应为术语或短语，不要返回课程内容包括、学习重点为等引导语，也不要返回完整句子。"
        "difficulty 只能是 basic、medium 或 hard。"
        f"\n课程：{course_title}\n学习目标：{learning_goal}\n资料摘要输入：{material_text}"
    )


def exercise_prompt(
    *,
    task_title: str,
    knowledge_point_titles: list[str],
    course_title: str = "",
    day_number: int = 1,
    code_context: bool | None = None,
) -> str:
    detected_code_context = any(
        term in f"{course_title} {' '.join(knowledge_point_titles)}".lower()
        for term in ("c语言", "指针", "结构体", "malloc", "free")
    )
    uses_code = detected_code_context if code_context is None else code_context
    third_format = "代码补全、代码阅读或找 Bug 题" if uses_code else "判断题"
    difficulty = "basic" if day_number <= 3 else "medium"
    return (
        "请基于当前学习任务生成正好3道练习题，返回 JSON。"
        "question_type 只能是 single_choice 或 short_answer。"
        "三题必须依次为：第一题简答、第二题单选、第三题" + third_format + "。"
        "优先覆盖不同知识点；知识点不足时允许复用，但不得复用题干、考查方式或提问模板。"
        f"三题 difficulty 必须全部为 {difficulty}。"
        "不要仅通过替换标点、空格或少量措辞重复同一问题。"
        "\n课程：" + course_title + "\n任务：" + task_title + "\n知识点：" + "、".join(knowledge_point_titles)
    )
