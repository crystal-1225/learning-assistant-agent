import httpx
import pytest

from demo.api_client import DemoApiClient, DemoApiError
from demo.app import (
    create_learning_plan,
    empty_session,
    load_agent_trace,
    load_full_plan,
    load_today_task,
    refresh_dashboard,
    submit_current_task,
)
from demo.formatters import (
    contains_answer_leak,
    format_create_plan_result,
    format_dashboard,
    format_dashboard_error,
    format_daily_tasks,
    format_health_markdown,
    format_mastery_records,
    format_plan,
    format_submission_result,
    format_today_task,
    format_trace,
)
from demo.state import DemoSessionState


class FakeClient:
    def __init__(self, **kwargs) -> None:
        self.timeout = kwargs.get("timeout")
        FakeTransport.client_kwargs.append(kwargs)

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *args) -> None:
        return None

    def request(self, method: str, url: str, json=None, **kwargs):
        FakeTransport.calls.append({"method": method, "url": url, "json": json, **kwargs})
        response = FakeTransport.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeTransport:
    calls: list[dict] = []
    responses: list[httpx.Response | Exception] = []
    client_kwargs: list[dict] = []


def install_fake_http(monkeypatch: pytest.MonkeyPatch) -> None:
    from demo import api_client

    FakeTransport.calls = []
    FakeTransport.responses = []
    FakeTransport.client_kwargs = []
    monkeypatch.setattr(api_client.httpx, "Client", FakeClient)


def json_response(status_code: int, payload: dict) -> httpx.Response:
    return httpx.Response(status_code=status_code, json=payload)


def json_any_response(status_code: int, payload) -> httpx.Response:
    return httpx.Response(status_code=status_code, json=payload)


def test_demo_api_client_health_parses_response(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_http(monkeypatch)
    FakeTransport.responses.append(json_response(200, {"status": "ok", "database": "ok", "service": "svc"}))
    data = DemoApiClient(base_url="http://backend").health()
    assert data["status"] == "ok"
    assert FakeTransport.calls[0]["method"] == "GET"
    assert FakeTransport.calls[0]["url"] == "http://backend/health"


def test_demo_api_client_disables_environment_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    from demo import api_client

    created_kwargs: list[dict] = []

    class ProxyAwareFakeClient(FakeClient):
        def __init__(self, **kwargs) -> None:
            created_kwargs.append(kwargs)
            self.timeout = kwargs.get("timeout")

    monkeypatch.setattr(api_client.httpx, "Client", ProxyAwareFakeClient)
    FakeTransport.calls = []
    FakeTransport.responses = [json_response(200, {"status": "ok", "database": "ok", "service": "svc"})]
    DemoApiClient(base_url="http://backend").health()
    assert created_kwargs[0]["trust_env"] is False


def test_base_url_with_health_is_not_double_joined(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_http(monkeypatch)
    FakeTransport.responses.append(json_response(200, {"status": "ok", "database": "ok", "service": "svc"}))
    DemoApiClient(base_url="http://backend/health").health()
    assert FakeTransport.calls[0]["url"] == "http://backend/health"


def test_create_user_request_format(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_http(monkeypatch)
    FakeTransport.responses.append(json_response(200, {"id": 1, "name": "演示用户"}))
    DemoApiClient(base_url="http://backend").create_user("演示用户")
    assert FakeTransport.calls[0]["json"] == {"name": "演示用户"}


def test_create_plan_request_format(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_http(monkeypatch)
    payload = {
        "user_id": 1,
        "course_title": "高等数学",
        "goal": "3天复习极限",
        "start_date": "2026-07-11",
        "end_date": "2026-07-13",
        "daily_minutes": 40,
        "material_text": "极限定义。",
    }
    FakeTransport.responses.append(json_response(200, {"plan": {"id": 1}}))
    DemoApiClient(base_url="http://backend").create_course_from_text(payload)
    assert FakeTransport.calls[0]["url"] == "http://backend/api/courses/from-text"
    assert FakeTransport.calls[0]["json"] == payload


def test_create_plan_request_filters_sensitive_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_http(monkeypatch)
    payload = {
        "user_id": 1,
        "course_title": "高等数学",
        "goal": "3天复习极限",
        "start_date": "2026-07-11",
        "end_date": "2026-07-13",
        "daily_minutes": 40,
        "material_text": "极限定义。",
        "standard_answer": "不应发送",
        "explanation": "不应发送",
        "api_key": "secret",
    }
    FakeTransport.responses.append(json_response(200, {"plan": {"id": 1}}))
    DemoApiClient(base_url="http://backend").create_course_from_text(payload)
    sent = FakeTransport.calls[0]["json"]
    assert "standard_answer" not in sent
    assert "explanation" not in sent
    assert "api_key" not in sent


def test_create_course_from_file_request_format(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_http(monkeypatch)
    FakeTransport.responses.append(json_response(200, {"plan": {"id": 1}}))
    payload = {
        "user_id": 1,
        "course_title": "高等数学",
        "goal": "3天复习极限",
        "start_date": "2026-07-11",
        "end_date": "2026-07-13",
        "daily_minutes": 40,
        "material_text": "补充文本",
    }
    DemoApiClient(base_url="http://backend").create_course_from_file(payload, "notes.docx", b"file-content")
    call = FakeTransport.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "http://backend/api/courses/from-file"
    assert call["data"]["user_id"] == "1"
    assert call["data"]["daily_minutes"] == "40"
    assert call["data"]["material_text"] == "补充文本"
    assert "standard_answer" not in call["data"]
    assert "notes.docx" in call["files"]["file"]


def test_create_course_from_file_omits_empty_material_text(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_http(monkeypatch)
    FakeTransport.responses.append(json_response(200, {"plan": {"id": 1}}))
    payload = {
        "user_id": 1,
        "course_title": "高等数学",
        "goal": "目标",
        "start_date": "2026-07-11",
        "end_date": "2026-07-13",
        "daily_minutes": 40,
        "material_text": None,
    }
    DemoApiClient(base_url="http://backend").create_course_from_file(payload, "notes.docx", b"file-content")
    call = FakeTransport.calls[0]
    assert "material_text" not in call["data"]
    assert set(call["data"]) == {"user_id", "course_title", "goal", "start_date", "end_date", "daily_minutes"}


def test_create_plan_with_file_uses_file_endpoint(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    file_path = tmp_path / "notes.docx"
    file_path.write_bytes(b"%PDF-fake-content")

    class FileClient(FakeDemoApiClient):
        def __init__(self, mode: str = "rule") -> None:
            super().__init__(mode)
            self.captured: dict = {}

        def create_course_from_file(self, payload: dict, filename: str, content: bytes) -> dict:
            self.captured["payload"] = payload
            self.captured["filename"] = filename
            self.captured["content"] = content
            return sample_creation_response(self.mode)

    fake = FileClient()
    monkeypatch.setattr("demo.app.DemoApiClient", lambda: fake)
    status, output, state = create_learning_plan(
        None,
        "演示用户",
        "高等数学",
        "3天复习极限",
        "2026-07-11",
        "2026-07-13",
        40,
        "",
        str(file_path),
    )
    assert "成功" in status
    assert fake.captured["filename"] == "notes.docx"
    assert fake.captured["content"] == b"%PDF-fake-content"
    assert state["plan_id"] == 13


def test_create_plan_requires_text_or_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("demo.app.DemoApiClient", lambda: FakeDemoApiClient(mode="rule"))
    status, output, state = create_learning_plan(
        None,
        "演示用户",
        "高等数学",
        "3天复习极限",
        "2026-07-11",
        "2026-07-13",
        40,
        "",
        None,
    )
    assert "错误" in status
    assert "上传" in output
    assert state["plan_id"] is None


def test_today_task_response_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_http(monkeypatch)
    FakeTransport.responses.append(json_response(200, {"status": "ok", "task": {"id": 2}}))
    data = DemoApiClient(base_url="http://backend").get_today_task(1)
    assert data["task"]["id"] == 2


def test_submit_payload_does_not_include_correct_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_http(monkeypatch)
    FakeTransport.responses.append(json_response(200, {"submission_id": 1}))
    DemoApiClient(base_url="http://backend").submit_task(
        5,
        completed=True,
        answers=[{"exercise_id": 1, "user_answer": "答案", "standard_answer": "不应发送"}],
        self_rating=3,
        notes="备注",
    )
    sent = FakeTransport.calls[0]["json"]
    assert "correct_rate" not in sent
    assert "is_correct" not in sent
    assert "mastery_score" not in sent
    assert "standard_answer" not in sent["answers"][0]


def test_unified_backend_error_is_displayed(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_http(monkeypatch)
    FakeTransport.responses.append(json_response(409, {"error": {"code": "TASK_ALREADY_SUBMITTED", "message": "已提交", "details": {}}}))
    with pytest.raises(DemoApiError) as exc:
        DemoApiClient(base_url="http://backend").health()
    assert "TASK_ALREADY_SUBMITTED" in str(exc.value)


def test_network_timeout_is_handled(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_http(monkeypatch)
    FakeTransport.responses.append(httpx.TimeoutException("timeout"))
    with pytest.raises(DemoApiError) as exc:
        DemoApiClient(base_url="http://backend").health()
    assert "超时" in str(exc.value)


def test_connection_failure_is_handled(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_http(monkeypatch)
    FakeTransport.responses.append(httpx.ConnectError("boom"))
    with pytest.raises(DemoApiError) as exc:
        DemoApiClient(base_url="http://backend").health()
    assert "后端" in str(exc.value)


def test_session_state_is_isolated() -> None:
    left = DemoSessionState()
    right = DemoSessionState()
    left.user_id = 1
    left.exercises.append({"id": 1})
    assert right.user_id is None
    assert right.exercises == []


def test_formatter_does_not_leak_answers_before_submit() -> None:
    text = format_health_markdown({"status": "ok", "database": "ok", "service": "svc"}, "http://backend")
    assert not contains_answer_leak(text)


def test_create_plan_saves_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("demo.app.DemoApiClient", lambda: FakeDemoApiClient(mode="rule"))
    status, output, state = create_learning_plan(
        None,
        "演示用户",
        "高等数学",
        "3天复习极限",
        "2026-07-11",
        "2026-07-13",
        40,
        "极限定义。重要极限。无穷小比较。",
    )
    assert "成功" in status
    assert "执行模式：rule" in status
    assert state["user_id"] == 7
    assert state["course_id"] == 11
    assert state["plan_id"] == 13
    assert state["task_id"] == 17
    assert len(state["exercises"]) == 3
    assert "计划 ID" in output


def test_two_create_plan_sessions_are_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("demo.app.DemoApiClient", lambda: FakeDemoApiClient(mode="llm"))
    _, _, first = create_learning_plan(None, "甲", "高数", "目标", "2026-07-11", "2026-07-13", 40, "资料")
    _, _, second = create_learning_plan(None, "乙", "英语", "目标", "2026-07-11", "2026-07-13", 40, "资料")
    first["exercises"].append({"id": 999})
    assert second["user_id"] == 7
    assert len(second["exercises"]) == 3


def test_create_plan_displays_exactly_three_exercises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("demo.app.DemoApiClient", lambda: FakeDemoApiClient(mode="rule"))
    _, output, _ = create_learning_plan(None, "演示用户", "高等数学", "目标", "2026-07-11", "2026-07-13", 40, "资料")
    assert output.count("[short_answer/basic]") == 3


def test_create_plan_output_does_not_leak_answers() -> None:
    output = format_create_plan_result(sample_creation_response("rule"), "http://backend")
    assert not contains_answer_leak(output)
    assert "标准答案" not in output
    assert "解析" not in output


@pytest.mark.parametrize("mode", ["rule", "llm", "fallback_rule"])
def test_execution_modes_are_displayed(mode: str) -> None:
    output = format_create_plan_result(sample_creation_response(mode), "http://backend")
    assert f"`{mode}`" in output


def test_create_plan_422_error_is_displayed(monkeypatch: pytest.MonkeyPatch) -> None:
    class ErrorClient(FakeDemoApiClient):
        def create_course_from_text(self, payload: dict) -> dict:
            raise DemoApiError("VALIDATION_ERROR: 参数校验失败")

    monkeypatch.setattr("demo.app.DemoApiClient", ErrorClient)
    status, output, state = create_learning_plan(None, "演示用户", "高等数学", "目标", "2026-07-11", "2026-07-13", 40, "资料")
    assert "错误" in status
    assert "VALIDATION_ERROR" in output
    assert state["plan_id"] is None


def test_create_plan_frontend_validation() -> None:
    status, output, state = create_learning_plan(None, "", "高等数学", "目标", "2026-07-11", "2026-07-13", 40, "资料")
    assert "错误" in status
    assert "用户名称不能为空" in output
    assert state["user_id"] is None


def test_get_today_task_request_is_correct(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_http(monkeypatch)
    FakeTransport.responses.append(json_response(200, sample_today_response()))
    data = DemoApiClient(base_url="http://backend").get_today_task(13)
    assert data["task"]["id"] == 17
    assert FakeTransport.calls[0]["method"] == "GET"
    assert FakeTransport.calls[0]["url"] == "http://backend/api/plans/13/today"


def test_today_task_displays_three_exercises() -> None:
    output = format_today_task(sample_today_response(), "http://backend")
    assert output.count("[short_answer/basic]") == 3
    assert not contains_answer_leak(output)


def test_load_today_task_updates_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("demo.app.DemoApiClient", lambda: FakeTodayClient())
    status, output, state, first, second, third = load_today_task({"plan_id": 13, "exercises": []})
    assert "成功" in status
    assert "今日任务已加载" in output
    assert state["task_id"] == 17
    assert len(state["exercises"]) == 3
    assert (first, second, third) == ("", "", "")


def test_load_today_task_without_plan_id_is_clear() -> None:
    status, output, state, *_ = load_today_task({})
    assert "错误" in status
    assert "先创建学习计划" in output
    assert state.get("plan_id") is None


def test_submit_request_excludes_sensitive_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_http(monkeypatch)
    FakeTransport.responses.append(json_response(200, sample_submission_response(correct_rate=1.0, weak=False)))
    DemoApiClient(base_url="http://backend").submit_task(
        17,
        completed=True,
        answers=[
            {
                "exercise_id": 1,
                "user_answer": "答案",
                "standard_answer": "不应发送",
                "explanation": "不应发送",
                "correct_rate": 1.0,
            }
        ],
        self_rating=5,
        notes="完成",
    )
    sent = FakeTransport.calls[0]["json"]
    assert set(sent) == {"completed", "answers", "self_rating", "notes"}
    assert set(sent["answers"][0]) == {"exercise_id", "user_answer"}


def test_submit_empty_answers_fails_frontend_validation() -> None:
    status, output, state = submit_current_task(sample_loaded_session(), "", "答案2", "答案3", 3, True, "")
    assert "错误" in status
    assert "填写所有练习题答案" in output
    assert state["latest_submission_id"] is None


def test_submit_self_rating_out_of_range_fails() -> None:
    status, output, _ = submit_current_task(sample_loaded_session(), "答案1", "答案2", "答案3", 6, True, "")
    assert "错误" in status
    assert "自评分必须在 1 到 5" in output


def test_perfect_submission_formats_no_remedial_adjustment() -> None:
    output = format_submission_result(sample_submission_response(correct_rate=1.0, weak=False), "http://backend")
    assert "总体正确率：**100%**" in output
    assert "全对，本轮不触发补救式调整" in output
    assert "本轮未发现明显薄弱点" in output
    assert not contains_answer_leak(output)


def test_wrong_submission_formats_weak_points() -> None:
    output = format_submission_result(sample_submission_response(correct_rate=0.33, weak=True), "http://backend")
    assert "正确题数：**0**" in output
    assert "总题数：**3**" in output
    assert "总体正确率：**33%**" in output
    assert "存在薄弱点" in output
    assert "极限定义" in output
    assert "是否触发计划调整：**已触发**" in output
    assert "第 2 天：重要极限" in output
    assert "本次执行模式：`rule`" in output
    assert "+0.0" in output or "-10.0" in output
    assert "standard_answer" not in output
    assert "sk-" not in output
    assert "Traceback" not in output


def test_duplicate_submission_is_friendly(monkeypatch: pytest.MonkeyPatch) -> None:
    class DuplicateClient(FakeTodayClient):
        def submit_task(self, *args, **kwargs) -> dict:
            raise DemoApiError("TASK_ALREADY_SUBMITTED: 已提交")

    monkeypatch.setattr("demo.app.DemoApiClient", DuplicateClient)
    status, output, _ = submit_current_task(sample_loaded_session(), "1", "2", "3", 3, True, "")
    assert "错误" in status
    assert "请勿重复提交" in output


def test_task_404_is_friendly(monkeypatch: pytest.MonkeyPatch) -> None:
    class NotFoundClient(FakeTodayClient):
        def submit_task(self, *args, **kwargs) -> dict:
            raise DemoApiError("RESOURCE_NOT_FOUND: task not found")

    monkeypatch.setattr("demo.app.DemoApiClient", NotFoundClient)
    status, output, _ = submit_current_task(sample_loaded_session(), "1", "2", "3", 3, True, "")
    assert "错误" in status
    assert "没有找到对应任务或计划" in output


def test_backend_422_is_friendly(monkeypatch: pytest.MonkeyPatch) -> None:
    class ValidationClient(FakeTodayClient):
        def submit_task(self, *args, **kwargs) -> dict:
            raise DemoApiError("VALIDATION_ERROR: 参数校验失败")

    monkeypatch.setattr("demo.app.DemoApiClient", ValidationClient)
    status, output, _ = submit_current_task(sample_loaded_session(), "1", "2", "3", 3, True, "")
    assert "错误" in status
    assert "校验失败" in output


def test_submit_saves_latest_result_in_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("demo.app.DemoApiClient", lambda: FakeTodayClient())
    status, output, state = submit_current_task(sample_loaded_session(), "1", "2", "3", 5, True, "完成")
    assert "成功" in status
    assert "提交成功" in output
    assert state["latest_submission_id"] == 501
    assert state["latest_submission_task_id"] == 17
    assert state["latest_correct_rate"] == 1.0
    assert state["latest_weak_points"] == []
    assert state["latest_adjustment_summary"]


def test_two_submission_sessions_are_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("demo.app.DemoApiClient", lambda: FakeTodayClient())
    _, _, left = submit_current_task(sample_loaded_session(), "1", "2", "3", 5, True, "")
    right = sample_loaded_session()
    left["latest_weak_points"].append({"id": 1})
    assert right["latest_submission_id"] is None
    assert right["latest_weak_points"] == []


def test_pre_submit_page_does_not_leak_answers() -> None:
    output = format_today_task(sample_today_response(include_sensitive=True), "http://backend")
    assert not contains_answer_leak(output)
    assert "标准答案" not in output


def test_get_plan_request_is_correct(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_http(monkeypatch)
    FakeTransport.responses.append(json_response(200, sample_plan_response()))
    data = DemoApiClient(base_url="http://backend").get_plan(13)
    assert data["plan"]["id"] == 13
    assert FakeTransport.calls[0]["method"] == "GET"
    assert FakeTransport.calls[0]["url"] == "http://backend/api/plans/13"


def test_get_trace_request_is_correct(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_http(monkeypatch)
    FakeTransport.responses.append(json_any_response(200, sample_trace_response()))
    data = DemoApiClient(base_url="http://backend").get_trace(13)
    assert len(data) == 3
    assert FakeTransport.calls[0]["url"] == "http://backend/api/plans/13/trace"


def test_get_trace_filters_are_encoded(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_http(monkeypatch)
    FakeTransport.responses.append(json_any_response(200, sample_trace_response()))
    DemoApiClient(base_url="http://backend").get_trace(13, task_id=17, status="failed", tool_name="content_parser")
    assert FakeTransport.calls[0]["url"] == "http://backend/api/plans/13/trace?task_id=17&status=failed&tool_name=content_parser"


def test_plan_formatting_includes_core_fields() -> None:
    output = format_plan(sample_plan_response(), "http://backend")
    assert "完整学习计划" in output
    assert "高等数学" in output
    assert "3天复习极限" in output
    assert "40 分钟" in output


def test_mastery_score_displays_zero_to_hundred() -> None:
    output = format_mastery_records(
        [{"id": 101, "title": "极限定义", "difficulty": "basic", "description": "理解"}],
        [{"knowledge_point_id": 101, "score": 135}],
    )
    assert "100.0/100" in output


def test_daily_task_status_labels_are_chinese() -> None:
    output = format_daily_tasks(sample_plan_response()["plan"]["daily_tasks"])
    assert "待完成" in output
    assert "已完成" in output
    assert "【已调整】" in output


def test_trace_execution_modes_are_chinese() -> None:
    output = format_trace(sample_trace_response())
    assert "规则模式" in output
    assert "大模型模式" in output
    assert "模型失败后规则兜底" in output


def test_trace_fallback_reason_only_when_present() -> None:
    output = format_trace(sample_trace_response())
    assert output.count("回退原因") == 1
    assert "JSON 无效" in output


def test_plan_page_does_not_leak_standard_answer() -> None:
    data = sample_plan_response()
    data["plan"]["daily_tasks"][0]["exercises"] = [{"standard_answer": "答案应包含x", "explanation": "本题用于检查x"}]
    output = format_plan(data, "http://backend")
    assert not contains_answer_leak(output)
    assert "standard_answer" not in output


def test_trace_page_does_not_leak_material_or_prompt() -> None:
    traces = sample_trace_response()
    traces[0]["output_summary"] = "完整课程资料：答案应包含敏感内容"
    output = format_trace(traces)
    assert "完整课程资料" not in output
    assert not contains_answer_leak(output)


def test_dashboard_without_plan_shows_welcome_and_backend_status() -> None:
    output = format_dashboard(empty_session(), health={"status": "ok", "database": "ok"})
    assert "欢迎使用大学生学习助手 Agent" in output
    assert "当前尚未创建学习计划" in output
    assert "● 后端在线" in output
    assert "Agent 学习建议" not in output


def test_dashboard_normal_plan_shows_real_overview_and_task_counts() -> None:
    plan_data = sample_plan_response()
    plan_data["plan"]["daily_tasks"].append(
        {
            "id": 19,
            "task_date": "2026-07-13",
            "title": "第 3 天：错题巩固",
            "status": "adjusted",
            "adjustment_reason": "根据本次提交识别薄弱知识点：重要极限",
        }
    )
    state = {"plan_id": 13, "user_name": "演示用户", "latest_weak_points": [], "latest_adjustment_summary": None}
    output = format_dashboard(state, plan_data, sample_today_response(), sample_trace_response(), {"status": "ok"})
    assert "演示用户" in output
    assert "高等数学" in output
    assert "3天复习极限" in output
    assert "2026-07-11 至 2026-07-13" in output
    assert "40 分钟" in output
    assert "计划总任务数" in output
    assert "已完成任务数" in output
    assert "待完成任务数" in output
    assert "已调整任务数" in output
    assert "33%" in output
    assert "今日学习" in output
    assert "计划时长：40 分钟" in output
    assert "下一任务" in output
    assert "待完成" in output
    assert "极限定义" in output
    assert "█████░░░░░" in output
    assert "最近 Agent 工具：exercise_generator" in output
    assert "最近执行模式：回退规则模式" in output
    assert "最近执行状态：失败" in output


def test_dashboard_adjusted_tasks_are_not_counted_as_completed() -> None:
    plan_data = sample_plan_response()
    plan_data["plan"]["daily_tasks"][1]["status"] = "adjusted"
    state = {"plan_id": 13, "user_name": "演示用户"}
    output = format_dashboard(state, plan_data, {"status": "all_completed", "task": None}, [], {"status": "ok"})
    assert "已完成任务数" in output
    assert "已调整任务数" in output
    assert "50%" in output


def test_dashboard_mastery_progress_bar_clamps_zero_fifty_and_one_hundred() -> None:
    plan_data = sample_plan_response()
    plan_data["knowledge_points"] = [
        {"id": 101, "title": "顺序表"},
        {"id": 102, "title": "链表"},
        {"id": 103, "title": "栈"},
    ]
    plan_data["mastery_records"] = [
        {"knowledge_point_id": 101, "score": -10},
        {"knowledge_point_id": 102, "score": 50},
        {"knowledge_point_id": 103, "score": 120},
    ]
    output = format_dashboard({"plan_id": 13, "user_name": "演示用户"}, plan_data, None, [], {"status": "ok"})

    assert "顺序表" in output and "░░░░░░░░░░" in output and "0%" in output
    assert "链表" in output and "█████░░░░░" in output and "50%" in output
    assert "栈" in output and "██████████" in output and "100%" in output


def test_dashboard_without_mastery_records_shows_specific_empty_state() -> None:
    plan_data = sample_plan_response()
    plan_data["mastery_records"] = []
    output = format_dashboard({"plan_id": 13, "user_name": "演示用户"}, plan_data, None, [], {"status": "ok"})

    assert "暂无掌握度记录" in output


def test_dashboard_advice_uses_real_weak_points_and_adjustments() -> None:
    plan_data = sample_plan_response()
    weak_state = {
        "plan_id": 13,
        "user_name": "演示用户",
        "latest_weak_points": [{"title": "极限定义", "mastery_score": 35, "reason": "本次正确率偏低"}],
    }
    weak_output = format_dashboard(weak_state, plan_data, sample_today_response(), [], {"status": "ok"})
    assert "建议优先复习：极限定义，完成补救任务后再继续新内容。" in weak_output

    plan_data["plan"]["daily_tasks"][1]["status"] = "adjusted"
    adjusted_state = {"plan_id": 13, "user_name": "演示用户", "latest_weak_points": []}
    adjusted_output = format_dashboard(adjusted_state, plan_data, sample_today_response(), [], {"status": "ok"})
    assert "系统已根据学习反馈调整后续计划，请关注调整后的任务安排。" in adjusted_output


def test_dashboard_all_completed_advice_is_deterministic() -> None:
    plan_data = sample_plan_response()
    for task in plan_data["plan"]["daily_tasks"]:
        task["status"] = "completed"
        task["adjustment_reason"] = None
    output = format_dashboard(
        {"plan_id": 13, "user_name": "演示用户", "latest_weak_points": []},
        plan_data,
        {"status": "all_completed", "task": None},
        [],
        {"status": "ok"},
    )
    assert "当前计划任务已完成，可以进行阶段复习或创建新的学习计划。" in output
    assert "当前计划已完成" in output


def test_dashboard_after_submission_uses_completed_task_and_future_next_task() -> None:
    plan_data = sample_plan_response()
    state = {
        "plan_id": 13,
        "user_name": "演示用户",
        "latest_submission_task_id": 17,
        "latest_weak_points": [],
        "latest_adjustment_summary": "本轮未调整。",
    }
    output = format_dashboard(state, plan_data, sample_today_response(), sample_trace_response(), {"status": "ok"})

    assert "任务状态：已完成" in output
    assert "第1天：极限定义" in output
    assert "第2天：重要极限" in output
    assert "完成当前任务后进入：" not in output


def test_dashboard_pending_today_does_not_repeat_it_as_next_task() -> None:
    plan_data = sample_plan_response()
    plan_data["plan"]["daily_tasks"][0]["status"] = "pending"
    output = format_dashboard(
        {"plan_id": 13, "user_name": "演示用户", "latest_weak_points": []},
        plan_data,
        sample_today_response(),
        [],
        {"status": "ok"},
    )

    assert "完成当前任务后进入：" in output
    assert output.count("第1天：极限复习") == 1
    assert "第2天：重要极限" in output


def test_dashboard_without_submission_has_explicit_feedback_and_adjustment_empty_states() -> None:
    plan_data = sample_plan_response()
    for task in plan_data["plan"]["daily_tasks"]:
        task["adjustment_reason"] = None
    output = format_dashboard(
        {"plan_id": 13, "user_name": "演示用户", "latest_weak_points": []},
        plan_data,
        sample_today_response(),
        [],
        {"status": "ok"},
    )

    assert "暂无学习反馈" in output
    assert "暂无薄弱点" in output
    assert "暂无调整" in output


def test_dashboard_offline_and_refresh_error_are_friendly() -> None:
    offline = format_dashboard(empty_session(), health=None)
    error = format_dashboard_error("刷新学习概览失败，请检查后端服务后重试。", health=None)

    assert "● 后端离线，请检查服务" in offline
    assert "● 后端离线，请检查服务" in error
    assert "Traceback" not in error
    assert "http://" not in error


def test_dashboard_missing_optional_data_and_sensitive_fields_are_not_displayed() -> None:
    plan_data = {
        "course": {"title": "高等数学"},
        "knowledge_points": [],
        "mastery_records": [],
        "plan": {
            "goal": "期末复习",
            "start_date": "2026-07-11",
            "end_date": "2026-07-13",
            "daily_minutes": 40,
            "daily_tasks": [
                {
                    "id": 17,
                    "task_date": "2026-07-11",
                    "title": "复习",
                    "status": "pending",
                    "standard_answer": "不得展示",
                    "database_path": "C:/private/app.db",
                }
            ],
        },
    }
    traces = [
        {
            "id": 1,
            "created_at": "2026-07-10T10:00:00",
            "tool_name": "content_parser",
            "execution_mode": "rule",
            "status": "success",
            "input_summary": "完整 prompt：不得展示",
            "output_summary": "Traceback: internal stack",
            "api_key": "sk-test-secret-should-not-leak",
        }
    ]
    output = format_dashboard({"plan_id": 13, "user_name": "演示用户"}, plan_data, None, traces, {"status": "ok"})
    assert output.count("暂无数据") >= 3
    assert "standard_answer" not in output
    assert "不得展示" not in output
    assert "prompt" not in output
    assert "Traceback" not in output
    assert "sk-test-secret-should-not-leak" not in output
    assert "C:/private/app.db" not in output
    assert not contains_answer_leak(output)


def test_dashboard_refresh_without_plan_is_friendly(monkeypatch: pytest.MonkeyPatch) -> None:
    class HealthClient:
        base_url = "http://backend"

        def health(self) -> dict:
            return {"status": "ok", "database": "ok"}

    monkeypatch.setattr("demo.app.DemoApiClient", HealthClient)
    status, output, state = refresh_dashboard({})
    assert "成功" in status
    assert "欢迎使用大学生学习助手 Agent" in output
    assert state.get("plan_id") is None


def test_load_full_plan_without_plan_id_is_clear() -> None:
    status, output, state = load_full_plan({})
    assert "错误" in status
    assert "先创建学习计划" in output
    assert state.get("plan_id") is None


def test_load_full_plan_404_is_friendly(monkeypatch: pytest.MonkeyPatch) -> None:
    class NotFoundClient(FakePlanTraceClient):
        def get_plan(self, plan_id: int) -> dict:
            raise DemoApiError("RESOURCE_NOT_FOUND: plan not found")

    monkeypatch.setattr("demo.app.DemoApiClient", NotFoundClient)
    status, output, _ = load_full_plan({"plan_id": 13})
    assert "错误" in status
    assert "没有找到对应任务或计划" in output


def test_load_trace_network_error_is_friendly(monkeypatch: pytest.MonkeyPatch) -> None:
    class NetworkClient(FakePlanTraceClient):
        def get_trace(self, *args, **kwargs) -> list[dict]:
            raise DemoApiError("无法连接后端服务，请检查后端地址、端口和网络。")

    monkeypatch.setattr("demo.app.DemoApiClient", NetworkClient)
    status, output, state = load_agent_trace({"plan_id": 13}, "", "全部", "全部")
    assert "错误" in status
    assert "无法连接后端服务" in output
    assert state["latest_trace_data"] == []


def test_load_plan_and_trace_sessions_are_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("demo.app.DemoApiClient", lambda: FakePlanTraceClient())
    _, _, left = load_full_plan({"plan_id": 13})
    _, _, right = load_full_plan({"plan_id": 13})
    left["latest_plan_data"]["course"]["title"] = "被修改"
    assert right["latest_plan_data"]["course"]["title"] == "高等数学"


def test_load_trace_filters_execution_mode_in_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("demo.app.DemoApiClient", lambda: FakePlanTraceClient())
    status, output, state = load_agent_trace({"plan_id": 13}, "", "全部", "fallback_rule")
    assert "成功" in status
    assert "模型失败后规则兜底" in output
    assert len(state["latest_trace_data"]) == 1
    assert state["selected_trace_filter"]["execution_mode"] == "fallback_rule"


class FakeDemoApiClient:
    base_url = "http://backend"

    def __init__(self, mode: str = "rule") -> None:
        self.mode = mode

    def create_user(self, name: str) -> dict:
        assert name
        return {"id": 7, "name": name}

    def create_course_from_text(self, payload: dict) -> dict:
        assert payload["user_id"] == 7
        return sample_creation_response(self.mode)


def sample_creation_response(mode: str) -> dict:
    return {
        "course": {"id": 11, "user_id": 7, "title": "高等数学", "description": None, "created_at": "2026-07-10T10:00:00"},
        "plan": {
            "id": 13,
            "course_id": 11,
            "goal": "3天复习极限",
            "start_date": "2026-07-11",
            "end_date": "2026-07-13",
            "daily_minutes": 40,
            "status": "active",
            "daily_tasks": [],
        },
        "knowledge_points": [
            {"id": 101, "course_id": 11, "title": "极限定义", "description": "理解极限定义", "difficulty": "basic"},
            {"id": 102, "course_id": 11, "title": "重要极限", "description": "掌握常见重要极限", "difficulty": "basic"},
        ],
        "today_task": {
            "id": 17,
            "plan_id": 13,
            "task_date": "2026-07-11",
            "title": "第1天：极限复习",
            "content": "学习极限定义和重要极限",
            "status": "pending",
            "knowledge_points": [],
            "exercises": [
                {"id": 1, "task_id": 17, "knowledge_point_id": 101, "question": "什么是极限定义？", "difficulty": "basic", "question_type": "short_answer"},
                {"id": 2, "task_id": 17, "knowledge_point_id": 102, "question": "写出一个重要极限。", "difficulty": "basic", "question_type": "short_answer"},
                {"id": 3, "task_id": 17, "knowledge_point_id": 101, "question": "极限计算时先看什么？", "difficulty": "basic", "question_type": "short_answer"},
            ],
        },
        "trace": [
            {
                "id": 1,
                "plan_id": 13,
                "task_id": None,
                "step": "parse_content",
                "tool_name": "content_parser",
                "reason_summary": "提取知识点",
                "input_summary": "课程笔记摘要",
                "output_summary": "提取2个知识点",
                "status": "success",
                "duration_ms": 12,
                "execution_mode": mode,
                "fallback_reason": "模型返回非法 JSON" if mode == "fallback_rule" else None,
                "created_at": "2026-07-10T10:00:00",
            }
        ],
    }


class FakeTodayClient:
    base_url = "http://backend"

    def get_today_task(self, plan_id: int) -> dict:
        assert plan_id == 13
        return sample_today_response()

    def submit_task(self, task_id: int, completed: bool, answers: list[dict], self_rating: int, notes: str | None) -> dict:
        assert task_id == 17
        assert completed is True
        assert len(answers) == 3
        assert self_rating in {1, 2, 3, 4, 5}
        return sample_submission_response(correct_rate=1.0, weak=False)


class FakePlanTraceClient:
    base_url = "http://backend"

    def get_plan(self, plan_id: int) -> dict:
        assert plan_id == 13
        return sample_plan_response()

    def get_trace(self, plan_id: int, task_id=None, status=None, tool_name=None) -> list[dict]:
        assert plan_id == 13
        traces = sample_trace_response()
        if status:
            traces = [trace for trace in traces if trace["status"] == status]
        if tool_name:
            traces = [trace for trace in traces if trace["tool_name"] == tool_name]
        return traces


def sample_loaded_session() -> dict:
    return {
        "user_id": 7,
        "course_id": 11,
        "plan_id": 13,
        "task_id": 17,
        "exercises": sample_today_response()["task"]["exercises"],
        "latest_submission_id": None,
        "latest_correct_rate": None,
        "latest_weak_points": [],
        "latest_adjustment_summary": None,
    }


def sample_today_response(include_sensitive: bool = False) -> dict:
    exercises = [
        {"id": 1, "task_id": 17, "knowledge_point_id": 101, "question": "什么是极限定义？", "difficulty": "basic", "question_type": "short_answer"},
        {"id": 2, "task_id": 17, "knowledge_point_id": 102, "question": "写出一个重要极限。", "difficulty": "basic", "question_type": "short_answer"},
        {"id": 3, "task_id": 17, "knowledge_point_id": 101, "question": "极限计算时先看什么？", "difficulty": "basic", "question_type": "short_answer"},
    ]
    if include_sensitive:
        exercises[0]["standard_answer"] = "标准答案不应展示"
        exercises[0]["explanation"] = "解析不应展示"
    return {
        "status": "ok",
        "message": None,
        "task": {
            "id": 17,
            "plan_id": 13,
            "task_date": "2026-07-11",
            "title": "第1天：极限复习",
            "content": "学习极限定义和重要极限",
            "status": "pending",
            "knowledge_points": [
                {"id": 101, "course_id": 11, "title": "极限定义", "description": "理解极限定义", "difficulty": "basic"}
            ],
            "exercises": exercises,
        },
    }


def sample_submission_response(correct_rate: float, weak: bool) -> dict:
    weak_points = (
        [
            {
                "id": 101,
                "title": "极限定义",
                "mastery_score": 35.0,
                "current_correct_rate": correct_rate,
                "reason": "本轮正确率偏低，需要巩固。",
            }
        ]
        if weak
        else []
    )
    return {
        "submission_id": 501,
        "task_id": 17,
        "completed": True,
        "correct_rate": correct_rate,
        "answer_results": [
            {"exercise_id": 1, "is_correct": correct_rate >= 1.0, "evaluation_reason": "根据关键词自动判定。"},
            {"exercise_id": 2, "is_correct": correct_rate >= 1.0, "evaluation_reason": "根据关键词自动判定。"},
            {"exercise_id": 3, "is_correct": correct_rate >= 1.0, "evaluation_reason": "根据关键词自动判定。"},
        ],
        "mastery_updates": [
            {
                "knowledge_point_id": 101,
                "knowledge_point_title": "极限定义",
                "old_score": 20.0,
                "new_score": 52.0 if not weak else 10.0,
                "score_change": 32.0 if not weak else -10.0,
                "correct_count": 3 if not weak else 1,
                "total_count": 3,
                "change_reason": "综合练习正确率、自评和完成情况更新。",
            }
        ],
        "weak_knowledge_points": weak_points,
        "adjustment_summary": "全对，本轮不调整后续计划。" if not weak else "已将薄弱知识点加入后续任务。",
        "adjusted_tasks": (
            [
                {
                    "id": 18,
                    "task_date": "2026-07-12",
                    "title": "第 2 天：重要极限",
                    "status": "adjusted",
                    "adjustment_reason": "薄弱知识点：极限定义；触发依据：本轮正确率偏低；调整内容：新增基础补救练习。",
                }
            ]
            if weak
            else []
        ),
        "trace": [
            {
                "id": 9,
                "plan_id": 13,
                "task_id": 17,
                "step": "evaluate_progress",
                "tool_name": "progress_evaluator",
                "reason_summary": "评估提交结果",
                "input_summary": "提交答案摘要",
                "output_summary": "生成反馈",
                "status": "success",
                "duration_ms": 8,
                "execution_mode": "rule",
                "created_at": "2026-07-10T10:00:00",
            }
        ],
    }


def sample_plan_response() -> dict:
    return {
        "course": {"id": 11, "user_id": 7, "title": "高等数学", "description": None, "created_at": "2026-07-10T10:00:00"},
        "knowledge_points": [
            {"id": 101, "course_id": 11, "title": "极限定义", "description": "理解极限定义", "difficulty": "basic"},
            {"id": 102, "course_id": 11, "title": "重要极限", "description": "掌握重要极限", "difficulty": "basic"},
        ],
        "mastery_records": [
            {"id": 1, "user_id": 7, "knowledge_point_id": 101, "old_score": 20, "new_score": 52, "score": 52, "confidence": 0.8, "change_reason": "全对提高"},
            {"id": 2, "user_id": 7, "knowledge_point_id": 102, "old_score": 20, "new_score": 16, "score": 16, "confidence": 0.4, "change_reason": "需要巩固"},
        ],
        "plan": {
            "id": 13,
            "course_id": 11,
            "goal": "3天复习极限",
            "start_date": "2026-07-11",
            "end_date": "2026-07-13",
            "daily_minutes": 40,
            "status": "active",
            "daily_tasks": [
                {
                    "id": 17,
                    "plan_id": 13,
                    "task_date": "2026-07-11",
                    "title": "第1天：极限定义",
                    "content": "学习极限定义",
                    "status": "completed",
                    "adjustment_reason": None,
                    "knowledge_points": [{"id": 101, "title": "极限定义", "course_id": 11, "description": "理解", "difficulty": "basic"}],
                    "exercises": [],
                },
                {
                    "id": 18,
                    "plan_id": 13,
                    "task_date": "2026-07-12",
                    "title": "第2天：重要极限",
                    "content": "复习重要极限",
                    "status": "pending",
                    "adjustment_reason": "根据本次提交识别薄弱知识点：重要极限",
                    "knowledge_points": [{"id": 102, "title": "重要极限", "course_id": 11, "description": "掌握", "difficulty": "basic"}],
                    "exercises": [],
                },
            ],
        },
    }


def sample_trace_response() -> list[dict]:
    return [
        {
            "id": 1,
            "plan_id": 13,
            "task_id": None,
            "created_at": "2026-07-10T10:00:00",
            "step": "分析目标",
            "tool_name": "goal_analyzer",
            "execution_mode": "rule",
            "status": "success",
            "duration_ms": 4,
            "reason_summary": "分析学习目标",
            "output_summary": "生成目标摘要",
            "fallback_reason": None,
        },
        {
            "id": 2,
            "plan_id": 13,
            "task_id": None,
            "created_at": "2026-07-10T10:00:01",
            "step": "解析内容",
            "tool_name": "content_parser",
            "execution_mode": "llm",
            "status": "success",
            "duration_ms": 80,
            "reason_summary": "提取知识点",
            "output_summary": "提取2个知识点",
            "provider": "openai_compatible",
            "model_name": "demo-model",
            "fallback_reason": None,
        },
        {
            "id": 3,
            "plan_id": 13,
            "task_id": 17,
            "created_at": "2026-07-10T10:00:02",
            "step": "生成练习",
            "tool_name": "exercise_generator",
            "execution_mode": "fallback_rule",
            "status": "failed",
            "duration_ms": 20,
            "reason_summary": "生成练习失败后兜底",
            "output_summary": "使用规则生成3题",
            "fallback_reason": "JSON 无效",
        },
    ]
