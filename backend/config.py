"""Typed environment configuration for the backend/ API layer only -- the
LLM provider precedence chain (ANTHROPIC_API_KEY / NVIDIA_API_KEY) stays in
llm/adapter.py's own build_adapter_from_env(), untouched by this module.

get_settings() builds a fresh Settings() on every call rather than caching
one -- the same "resolve at call time, not def time" choice backend/db.py
already makes for DEFAULT_DB_PATH, so tests can monkeypatch.setenv without
needing a separate cache-clear step.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MANIFEST_")

    api_keys: str = ""
    cors_origins: str = "http://localhost:8501"
    log_level: str = "INFO"
    log_json: bool = True

    @property
    def api_key_set(self) -> frozenset[str]:
        return frozenset(k.strip() for k in self.api_keys.split(",") if k.strip())

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


def get_settings() -> Settings:
    return Settings()
