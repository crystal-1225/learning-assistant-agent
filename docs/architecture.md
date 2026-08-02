# 系统总体架构

本图只描述当前已实现的组件与数据流。当前演示默认使用规则模式；OpenAI Compatible LLM 是可选的兼容接口，不是系统运行的前提。

```mermaid
flowchart TB
    student[大学生用户]

    subgraph presentation[用户与表现层]
        demo[Gradio Web Demo]
        dashboard[学习概览 Dashboard]
        create[创建学习计划]
        today[今日任务与答题]
        plan_view[学习计划]
        trace_view[Agent 执行轨迹]
        demo --> dashboard
        demo --> create
        demo --> today
        demo --> plan_view
        demo --> trace_view
    end

    subgraph api_layer[API 与服务层]
        api[FastAPI Backend]
        users_api[用户接口]
        courses_api[课程接口]
        plans_api[计划接口]
        tasks_api[任务提交接口]
        health[健康检查接口]
        api --> users_api
        api --> courses_api
        api --> plans_api
        api --> tasks_api
        api --> health
    end

    subgraph orchestration[Agent 编排层]
        plan_orch[Learning Plan Orchestrator]
        submit_orch[Submission Orchestrator]
        trace_recorder[Trace Recorder]
    end

    subgraph plan_tools[学习计划生成工具]
        goal[Goal Analyzer]
        parser[Content Parser V2]
        planner[Plan Generator]
        task_gen[Task Generator]
        exercise_gen[Exercise Generator V3]
    end

    subgraph feedback_tools[学习反馈工具]
        evaluator[Answer Evaluator]
        progress[Progress Evaluator]
        weak[Weak Point Detector]
        replanner[Replanner]
    end

    subgraph data_layer[数据与模型层]
        sqlite[(SQLite)]
        users[Users]
        courses[Courses 与 Materials]
        plans[Plans]
        tasks[Tasks]
        exercises[Exercises]
        submissions[Submissions]
        mastery[Knowledge Mastery]
        traces[Agent Trace]
        sqlite --- users
        sqlite --- courses
        sqlite --- plans
        sqlite --- tasks
        sqlite --- exercises
        sqlite --- submissions
        sqlite --- mastery
        sqlite --- traces
    end

    subgraph optional_llm[可选 LLM 层]
        llm[OpenAI Compatible LLM<br/>预留兼容接口]
        rule_note[当前演示：rule 模式<br/>调用失败：fallback_rule]
    end

    student --> demo
    demo --> api
    courses_api --> plan_orch
    tasks_api --> submit_orch
    plans_api --> sqlite
    users_api --> sqlite
    health --> sqlite

    plan_orch --> goal --> parser --> planner --> task_gen --> exercise_gen
    submit_orch --> evaluator --> progress --> weak --> replanner
    plan_orch --> trace_recorder
    submit_orch --> trace_recorder

    goal --> sqlite
    parser --> sqlite
    planner --> sqlite
    task_gen --> sqlite
    exercise_gen --> sqlite
    evaluator --> sqlite
    progress --> sqlite
    weak --> sqlite
    replanner --> sqlite
    trace_recorder --> traces

    llm -. 可选结构化调用 .-> goal
    llm -. 可选结构化调用 .-> parser
    llm -. 可选结构化调用 .-> exercise_gen
    goal -. 失败回退 .-> rule_note
    parser -. 失败回退 .-> rule_note
    exercise_gen -. 失败回退 .-> rule_note
```

## 说明

- Gradio 通过现有 HTTP 接口读取计划、今日任务和轨迹，并提交答题结果；Dashboard 只展示这些真实数据与当前浏览器 session 的最近提交结果。
- `Learning Plan Orchestrator` 负责课程文本到计划、首日练习和掌握度初始值的创建链路；`Submission Orchestrator` 负责提交后的评价、掌握度更新、薄弱点识别和重规划。
- SQLite 保存用户、课程资料、知识点、计划、任务、练习、提交、掌握度记录和 Agent Trace。图中的 “Plans”“Tasks” 等是表的业务归类，不代表额外服务。
- 配置 LLM 时仅由目标分析、内容解析和练习生成使用结构化调用；请求失败、结构化校验失败或未配置时回退规则工具。当前文档不宣称已进行真实 LLM 调用。
