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
    def api_key_labels(self) -> dict[str, str]:
        """Maps each configured key to a caller label, so the audit log can
        record who called an endpoint, not just what happened. Entries are
        "label:key" pairs; a bare entry with no ":" is its own label, for
        backward compatibility with configs written before labels existed."""
        labels: dict[str, str] = {}
        for entry in self.api_keys.split(","):
            entry = entry.strip()
            if not entry:
                continue
            label, _, key = entry.partition(":")
            labels[key or label] = label
        return labels

    @property
    def api_key_set(self) -> frozenset[str]:
        return frozenset(self.api_key_labels.keys())

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


def get_settings() -> Settings:
    return Settings()
