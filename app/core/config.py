from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


API_KEY_PLACEHOLDERS = {"replace-with-your-api-key", "your-api-key", "changeme"}


class Settings(BaseSettings):
    app_name: str = "智学环 Agent Backend"
    database_url: str = f"sqlite:///{Path(__file__).resolve().parents[2] / 'data' / 'app.db'}"
    llm_enabled: bool = False
    llm_provider: str = "openai_compatible"
    llm_model: str = "gpt-4.1-mini"
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    llm_max_retries: int = Field(default=2, ge=1, le=5)
    llm_max_input_chars: int = Field(default=8000, gt=0, le=50000)
    llm_max_output_chars: int = Field(default=12000, gt=0, le=50000)
    max_file_mb: int = Field(default=10, gt=0, le=100)
    max_file_chars: int = Field(default=50000, gt=0, le=200000)
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:8000"

    model_config = SettingsConfigDict(env_prefix="ZHIXUEHUAN_", env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @field_validator("llm_base_url")
    @classmethod
    def llm_base_url_must_be_http_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("llm_base_url must be an absolute http(s) URL")
        if parsed.username or parsed.password:
            raise ValueError("llm_base_url must not contain credentials")
        return normalized

    @property
    def has_llm_api_key(self) -> bool:
        value = (self.llm_api_key or "").strip()
        return bool(value) and value.lower() not in API_KEY_PLACEHOLDERS

    @property
    def llm_base_url_safe(self) -> str:
        parsed = urlparse(self.llm_base_url)
        return parsed.netloc or "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()
