# 智学环后端 API Contract

本文件冻结当前鸿蒙端可依赖的后端接口。所有响应均不得返回 `standard_answer`、`explanation`、完整课程资料、API key、Authorization header 或内部堆栈。

## 统一错误格式

```json
{
  "error": {
    "code": "TASK_ALREADY_SUBMITTED",
    "message": "task has already been submitted",
    "details": {}
  }
}
```

常见状态码：`400` 请求不合法，`404` 资源不存在，`409` 重复提交，`422` 参数校验失败，`500` 服务内部错误。

## POST /api/users

请求：

```json
{ "name": "演示用户" }
```

成功响应：

```json
{ "id": 1, "name": "演示用户", "created_at": "2026-07-10T10:00:00" }
```

鸿蒙端可用字段：`id`、`name`、`created_at`。

## POST /api/courses/from-text

请求：

```json
{
  "user_id": 1,
  "course_title": "高等数学",
  "goal": "3天复习极限，准备小测",
  "start_date": "2026-07-11",
  "end_date": "2026-07-13",
  "daily_minutes": 40,
  "material_text": "极限定义。重要极限。无穷小比较。"
}
```

成功响应包含：

```json
{
  "course": {},
  "plan": {},
  "knowledge_points": [],
  "today_task": { "exercises": [] },
  "trace": []
}
```

鸿蒙端可用字段：课程、计划、知识点、今日任务、公开练习题、trace 展示字段。

## GET /api/plans/{plan_id}

成功响应包含：`plan`、`course`、`knowledge_points`、`mastery_records`。任务按日期排序，练习只返回公开字段。

## GET /api/plans/{plan_id}/today

成功响应：

```json
{ "status": "ok", "task": {}, "message": null }
```

所有任务完成：

```json
{ "status": "all_completed", "task": null, "message": "所有任务已完成" }
```

## POST /api/tasks/{task_id}/submit

请求：

```json
{
  "completed": true,
  "answers": [
    { "exercise_id": 1, "user_answer": "我的答案" }
  ],
  "self_rating": 3,
  "notes": "重要极限仍然不熟"
}
```

成功响应包含：`submission_id`、`correct_rate`、`answer_results`、`mastery_updates`、`weak_knowledge_points`、`adjustment_summary`、`trace`。

重复提交返回 `409`。

## GET /api/plans/{plan_id}/trace

可选 query：`task_id`、`status`、`tool_name`。

trace 可展示字段包括：`step`、`tool_name`、`execution_mode`、`provider`、`model_name`、`fallback_reason`、`duration_ms`、`request_id`、`retry_count`、字符数和 token usage。不得展示 prompt 或资料全文。

## GET /health

成功响应：

```json
{
  "status": "ok",
  "database": "ok",
  "service": "zhixuehuan-agent-backend"
}
```

