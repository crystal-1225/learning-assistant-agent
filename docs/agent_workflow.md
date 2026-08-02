# Agent 工作流与学习闭环

下图展示当前实现的两条主链路：创建学习计划，以及答题后的学习反馈与动态重规划。

```mermaid
flowchart TB
    subgraph creation[创建学习计划]
        input[用户输入：课程、学习目标、日期、每日时长、课程笔记]
        goal[Goal Analyzer]
        parser[Content Parser V2]
        planner[Plan Generator]
        task_gen[Task Generator]
        exercise_gen[Exercise Generator V3]
        save_plan[保存课程、知识点、计划、任务、首日练习<br/>并初始化掌握度]
        creation_update[更新 Dashboard 与 Agent Trace]

        input --> goal --> parser --> planner --> task_gen --> exercise_gen --> save_plan --> creation_update
    end

    subgraph feedback[学习反馈与动态重规划]
        submit[用户完成练习并提交]
        validate[Validate Submission]
        duplicate{该任务是否已经提交？}
        conflict[返回 409<br/>不重复累计掌握度]
        answer[Answer Evaluator]
        save_submission[保存提交记录与逐题判定]
        progress[Progress Evaluator]
        weak[Weak Point Detector]
        weak_decision{是否识别出薄弱知识点？}
        keep[保持当前计划]
        replan[Replanner]
        future_only[只调整未来未完成任务]
        remedial[插入或补充针对性补救内容]
        reason[记录 adjustment_reason]
        feedback_update[更新 Dashboard 与 Agent Trace]

        submit --> validate --> duplicate
        duplicate -- 是 --> conflict
        duplicate -- 否 --> answer --> save_submission --> progress --> weak --> weak_decision
        weak_decision -- 否 --> keep --> feedback_update
        weak_decision -- 是 --> replan --> future_only --> remedial --> reason --> feedback_update
    end

    thresholds[薄弱点规则：<br/>正确率低于 0.6：weak<br/>0.6 至 0.8 且新掌握度低于 60：weak<br/>正确率达到或超过 0.8：不触发 weak]
    modes[执行模式：rule、llm、fallback_rule<br/>当前演示环境使用 rule]

    weak --> thresholds
    goal -. 记录执行模式 .-> modes
    parser -. 记录执行模式 .-> modes
    exercise_gen -. 记录执行模式 .-> modes
    answer -. 记录执行模式 .-> modes

    feedback_update --> next_round[继续下一轮学习]
```

## 闭环含义

1. 系统感知用户提交的练习答案并计算正确率。
2. 系统按知识点更新掌握度，再根据正确率与新掌握度识别薄弱点。
3. 无薄弱点时保持计划；有薄弱点时只修改未来、未完成的任务，避免改写已完成任务或当天已提交任务。
4. 重规划会避免重复加入相同补救内容，并把薄弱知识点、触发依据和调整内容写入 `adjustment_reason`。
5. 每轮结果通过 Dashboard 和 Agent Trace 展示，形成“感知结果 → 分析状态 → 调整决策 → 修改未来计划 → 继续学习”的闭环。

## LLM 与规则模式

目标分析、内容解析和练习生成支持 `rule`、`llm`、`fallback_rule` 三种执行模式。当前演示使用规则模式；可选 LLM 的调用失败或返回无效结构化结果时，系统会使用 `fallback_rule` 完成同一流程。
