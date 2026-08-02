import json
from uuid import uuid4
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.llm.base import LLMCallMetadata, LLMClient
from app.llm.exceptions import LLMConfigurationError, LLMInvalidResponseError, LLMRequestError


T = TypeVar("T", bound=BaseModel)


class OpenAICompatibleLLMClient(LLMClient):
    def __init__(self, settings: Settings) -> None:
        if not settings.has_llm_api_key:
            raise LLMConfigurationError("LLM API key is not configured")
        self.provider = settings.llm_provider
        self.model_name = settings.llm_model
        self.base_url = settings.llm_base_url.rstrip("/")
        self.api_key = settings.llm_api_key
        self.timeout_seconds = settings.llm_timeout_seconds
        self.max_retries = settings.llm_max_retries
        self.max_input_chars = settings.llm_max_input_chars
        self.max_output_chars = settings.llm_max_output_chars
        self.last_call_metadata = None

    def generate_structured(self, *, prompt: str, response_model: type[T], timeout_seconds: float | None = None) -> T:
        if len(prompt) > self.max_input_chars:
            self.last_call_metadata = LLMCallMetadata(
                request_id=f"llm_{uuid4().hex[:16]}",
                retry_count=0,
                input_char_count=len(prompt),
            )
            raise LLMInvalidResponseError("LLM prompt exceeded max input length")

        last_error: Exception | None = None
        request_id = f"llm_{uuid4().hex[:16]}"
        last_attempt_index = 0
        for attempt_index in range(self.max_retries):
            last_attempt_index = attempt_index
            try:
                payload = {
                    "model": self.model_name,
                    "messages": [
                        {"role": "system", "content": "你只输出可解析 JSON，不输出解释。"},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                }
                with httpx.Client(timeout=timeout_seconds or self.timeout_seconds, trust_env=False) as client:
                    response = client.post(
                        f"{self.base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json=payload,
                    )
                    response.raise_for_status()
                response_json = response.json()
                content = response_json["choices"][0]["message"]["content"]
                if len(content) > self.max_output_chars:
                    self.last_call_metadata = LLMCallMetadata(
                        request_id=request_id,
                        retry_count=attempt_index,
                        input_char_count=len(prompt),
                        output_char_count=len(content),
                    )
                    raise LLMInvalidResponseError("LLM response exceeded max output length")
                usage = response_json.get("usage") or {}
                self.last_call_metadata = LLMCallMetadata(
                    request_id=request_id,
                    retry_count=attempt_index,
                    input_char_count=len(prompt),
                    output_char_count=len(content),
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                    total_tokens=usage.get("total_tokens"),
                )
                return response_model.model_validate_json(content)
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code in {401, 403}:
                    break
            except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
                last_error = exc
            except (json.JSONDecodeError, ValidationError) as exc:
                self.last_call_metadata = LLMCallMetadata(
                    request_id=request_id,
                    retry_count=attempt_index,
                    input_char_count=len(prompt),
                    output_char_count=None,
                )
                raise LLMInvalidResponseError("LLM response failed structured validation") from None
        self.last_call_metadata = LLMCallMetadata(
            request_id=request_id,
            retry_count=last_attempt_index,
            input_char_count=len(prompt),
            output_char_count=None,
        )
        raise LLMRequestError("LLM request failed") from None


def get_llm_client() -> LLMClient | None:
    settings = get_settings()
    if not settings.llm_enabled:
        return None
    if not settings.has_llm_api_key:
        return None
    return OpenAICompatibleLLMClient(settings)
