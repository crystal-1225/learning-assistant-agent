# Gradio 演示界面指南

第 5.1 步只实现最简首页和后端 `/health` 检查。

## 启动后端

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 启动 Gradio

```powershell
$env:ZHIXUEHUAN_BACKEND_URL="http://127.0.0.1:8000"
.\.venv\Scripts\python.exe demo\app.py
```

打开：

```text
http://127.0.0.1:7860
```

## 502 排查

如果浏览器直接访问 `http://127.0.0.1:8000/health` 正常，但 Gradio 页面显示 502，优先检查系统代理。`DemoApiClient` 已设置 `trust_env=False`，不会读取 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 等环境代理。

后端地址只配置服务根地址，例如：

```text
http://127.0.0.1:8000
```

不要配置成：

```text
http://127.0.0.1:8000/health
```

代码会兼容误填的 `/health`，但推荐保持根地址清晰。

## 当前功能

- 显示作品名称
- 真实请求 FastAPI `/health`
- 展示服务状态和数据库状态
- 显示 loading / success / error

## 暂未实现

- 创建学习计划
- 今日任务
- 提交答案
- Agent 轨迹完整展示
