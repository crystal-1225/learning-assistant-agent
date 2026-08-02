from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import TypeVar

from app.models.entities import AgentTrace, TraceStatus


T = TypeVar("T")


@dataclass
class TraceDraft:
    step: str
    tool_name: str
    reason_summary: str
    input_summary: str
    output_summary: str
    status: str
    duration_ms: int
    task_id: int | None = None
    execution_mode: str = "rule"
    provider: str | None = None
    model_name: str | None = None
    fallback_reason: str | None = None
    request_id: str | None = None
    retry_count: int = 0
    input_char_count: int | None = None
    output_char_count: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class TraceRecorder:
    def __init__(self) -> None:
        self._drafts: list[TraceDraft] = []

    @property
    def drafts(self) -> list[TraceDraft]:
        return self._drafts

    def run(
        self,
        *,
        step: str,
        tool_name: str,
        reason_summary: str,
        input_summary: str,
        output_summary: Callable[[T], str],
        func: Callable[[], T],
        task_id: int | None = None,
        execution_mode: str = "rule",
        provider: str | None = None,
        model_name: str | None = None,
        fallback_reason: str | None = None,
        metadata: Callable[[T], dict[str, str | None]] | None = None,
    ) -> T:
        started = perf_counter()
        try:
            result = func()
        except Exception as exc:
            self._drafts.append(
                TraceDraft(
                    step=step,
                    tool_name=tool_name,
                    reason_summary=reason_summary,
                    input_summary=input_summary,
                    output_summary=f"工具执行失败：{exc.__class__.__name__}",
                    status=TraceStatus.FAILED.value,
                    duration_ms=_elapsed_ms(started),
                    task_id=task_id,
                    execution_mode=execution_mode,
                    provider=provider,
                    model_name=model_name,
                fallback_reason=exc.__class__.__name__,
            )
            )
            raise

        trace_metadata = metadata(result) if metadata is not None else {}
        self._drafts.append(
            TraceDraft(
                step=step,
                tool_name=tool_name,
                reason_summary=reason_summary,
                input_summary=input_summary,
                output_summary=output_summary(result),
                status=TraceStatus.SUCCESS.value,
                duration_ms=_elapsed_ms(started),
                task_id=task_id,
                execution_mode=trace_metadata.get("execution_mode") or execution_mode,
                provider=trace_metadata.get("provider") or provider,
                model_name=trace_metadata.get("model_name") or model_name,
                fallback_reason=trace_metadata.get("fallback_reason") or fallback_reason,
                request_id=trace_metadata.get("request_id"),
                retry_count=int(trace_metadata.get("retry_count") or 0),
                input_char_count=_optional_int(trace_metadata.get("input_char_count")),
                output_char_count=_optional_int(trace_metadata.get("output_char_count")),
                prompt_tokens=_optional_int(trace_metadata.get("prompt_tokens")),
                completion_tokens=_optional_int(trace_metadata.get("completion_tokens")),
                total_tokens=_optional_int(trace_metadata.get("total_tokens")),
            )
        )
        return result

    def to_entities(self, plan_id: int) -> list[AgentTrace]:
        return [
            AgentTrace(
                plan_id=plan_id,
                task_id=draft.task_id,
                step=draft.step,
                tool_name=draft.tool_name,
                reason_summary=draft.reason_summary,
                input_summary=draft.input_summary,
                output_summary=draft.output_summary,
                status=draft.status,
                duration_ms=draft.duration_ms,
                execution_mode=draft.execution_mode,
                provider=draft.provider,
                model_name=draft.model_name,
                fallback_reason=draft.fallback_reason,
                request_id=draft.request_id,
                retry_count=draft.retry_count,
                input_char_count=draft.input_char_count,
                output_char_count=draft.output_char_count,
                prompt_tokens=draft.prompt_tokens,
                completion_tokens=draft.completion_tokens,
                total_tokens=draft.total_tokens,
            )
            for draft in self._drafts
        ]


def _elapsed_ms(started: float) -> int:
    return max(0, int((perf_counter() - started) * 1000))


def _optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
