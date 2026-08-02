from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel


T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class LLMCallMetadata:
    request_id: str
    retry_count: int
    input_char_count: int
    output_char_count: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class LLMClient(ABC):
    provider: str
    model_name: str
    last_call_metadata: LLMCallMetadata | None = None

    @abstractmethod
    def generate_structured(self, *, prompt: str, response_model: type[T], timeout_seconds: float | None = None) -> T:
        raise NotImplementedError
