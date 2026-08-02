import os
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx


class DemoApiError(Exception):
    """User-facing API error for the Gradio demo."""


class DemoApiClient:
    def __init__(self, base_url: str | None = None, timeout_seconds: float = 8.0) -> None:
        self.base_url = _normalize_base_url(base_url or os.getenv("ZHIXUEHUAN_BACKEND_URL") or "http://127.0.0.1:8000")
        self.timeout_seconds = timeout_seconds

    def health(self) -> dict[str, Any]:
        return self.get("/health")

    def create_user(self, name: str) -> dict[str, Any]:
        return self.post("/api/users", {"name": name.strip()})

    def create_course_from_text(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed_fields = (
            "user_id",
            "course_title",
            "goal",
            "start_date",
            "end_date",
            "daily_minutes",
            "material_text",
        )
        safe_payload = {field: payload[field] for field in allowed_fields if field in payload}
        return self.post("/api/courses/from-text", safe_payload)

    def get_today_task(self, plan_id: int) -> dict[str, Any]:
        return self.get(f"/api/plans/{plan_id}/today")

    def get_plan(self, plan_id: int) -> dict[str, Any]:
        return self.get(f"/api/plans/{plan_id}")

    def get_trace(
        self,
        plan_id: int,
        task_id: int | None = None,
        status: str | None = None,
        tool_name: str | None = None,
    ) -> list[dict[str, Any]]:
        params = {
            key: value
            for key, value in {"task_id": task_id, "status": status, "tool_name": tool_name}.items()
            if value not in (None, "")
        }
        query = f"?{urlencode(params)}" if params else ""
        data = self._request("GET", f"/api/plans/{plan_id}/trace{query}")
        if not isinstance(data, list):
            raise DemoApiError("后端返回格式不符合预期。")
        return data

    def submit_task(
        self,
        task_id: int,
        completed: bool,
        answers: list[dict[str, Any]],
        self_rating: int,
        notes: str | None,
    ) -> dict[str, Any]:
        safe_answers = [
            {
                "exercise_id": int(answer["exercise_id"]),
                "user_answer": str(answer.get("user_answer", "")).strip(),
            }
            for answer in answers
            if "exercise_id" in answer
        ]
        safe_payload = {
            "completed": bool(completed),
            "answers": safe_answers,
            "self_rating": int(self_rating),
            "notes": notes.strip() if isinstance(notes, str) and notes.strip() else None,
        }
        return self.post(f"/api/tasks/{task_id}/submit", safe_payload)

    def get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path)

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, payload)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any] | list[dict[str, Any]]:
        url = f"{self.base_url}{path if path.startswith('/') else '/' + path}"
        try:
            with httpx.Client(timeout=self.timeout_seconds, trust_env=False) as client:
                response = client.request(method, url, json=payload)
        except httpx.TimeoutException as exc:
            raise DemoApiError("连接后端超时，请确认 FastAPI 服务已启动且地址正确。") from exc
        except httpx.HTTPError as exc:
            raise DemoApiError("无法连接后端服务，请检查后端地址、端口和网络。") from exc

        if response.status_code >= 400:
            raise DemoApiError(_format_backend_error(response))

        try:
            data = response.json()
        except ValueError as exc:
            raise DemoApiError("后端返回了无法解析的数据。") from exc

        if not isinstance(data, (dict, list)):
            raise DemoApiError("后端返回格式不符合预期。")
        return data


def _format_backend_error(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return f"后端请求失败：HTTP {response.status_code}"

    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        code = error.get("code", "BACKEND_ERROR")
        message = error.get("message", "后端请求失败")
        return f"{code}: {message}"
    return f"后端请求失败：HTTP {response.status_code}"


def _normalize_base_url(raw_base_url: str) -> str:
    value = raw_base_url.strip()
    if not value:
        value = "http://127.0.0.1:8000"
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        raise DemoApiError("后端地址格式不正确，请使用类似 http://127.0.0.1:8000 的地址。")
    path = parsed.path.rstrip("/")
    if path == "/health":
        path = ""
    normalized = urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
    return normalized.rstrip("/")
