"""Provider-agnostic LLM adapter. The rest of the codebase depends only on
the LLMAdapter protocol, never on a concrete provider -- and core/ depends
on neither (CLAUDE.md rule 2: core/ must never import llm/).

Settings: temperature=0, a pinned model string, capped max_tokens, and at
most one retry on schema validation failure before giving up and letting
the caller fall back to a deterministic default (CLAUDE.md rule 4).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger("manifest.llm")

T = TypeVar("T", bound=BaseModel)

TEMPERATURE = 0
MAX_TOKENS = 1024
PINNED_MODEL = "claude-sonnet-5"
NVIDIA_PINNED_MODEL = "deepseek-ai/deepseek-v4-pro-0813"  # via NVIDIA's NIM endpoint
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
MAX_RETRIES = 1  # one retry maximum on schema failure, then give up


class LLMAdapter(Protocol):
    model_string: str

    def complete(self, system: str, user: str, schema: type[T]) -> T | None:
        """Returns a validated instance of `schema`, or None if the
        provider is unavailable or every attempt failed schema validation.
        Callers must have a deterministic fallback for the None case."""
        ...


class NullAdapter:
    """Used when --no-llm is set or no API key is present. Always returns
    None, so every caller's deterministic fallback path is exercised on
    every run -- this is what makes --no-llm a real, tested code path
    rather than a flag no test ever takes."""

    model_string = "none"

    def complete(self, system: str, user: str, schema: type[T]) -> T | None:
        return None


def _parse_response(text: str, schema: type[T]) -> T:
    """Shared JSON-parse-and-validate step for every provider. Validates
    with strict=False even though every schema in llm/schemas.py sets
    strict=True in its own model_config -- that's the right default for
    constructing these objects from already-typed Python values elsewhere,
    but it's fundamentally incompatible with parsing real external JSON:
    JSON has no enum type, so NarrationClassification.narration_type
    always arrives as a plain string like "SETTLEMENT", and strict mode's
    is_instance_of check on an Enum field rejects that unconditionally --
    not a plausible-but-wrong value, every real provider response, always.
    strict=False here restores the intended lax-JSON-input coercion
    (string -> enum, string -> float, etc.) without touching the schema's
    own strict=True, which still applies to any other construction path
    (e.g. tests building one directly in Python)."""
    data = json.loads(text)
    return schema.model_validate(data, strict=False)


class AnthropicAdapter:
    """Talks to the real Anthropic API. Requires the `anthropic` package
    and an API key; both are only ever needed here, never in core/."""

    def __init__(self, api_key: str, model: str = PINNED_MODEL):
        import anthropic  # deferred: only llm/ needs this dependency at runtime

        self._client = anthropic.Anthropic(api_key=api_key)
        self.model_string = model

    def complete(self, system: str, user: str, schema: type[T]) -> T | None:
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = self._client.messages.create(
                    model=self.model_string,
                    max_tokens=MAX_TOKENS,
                    temperature=TEMPERATURE,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                text = "".join(
                    block.text
                    for block in response.content
                    if getattr(block, "type", None) == "text"
                )
                return _parse_response(text, schema)
            except (ValidationError, json.JSONDecodeError, KeyError, AttributeError) as exc:
                last_error = exc
                logger.warning(
                    "LLM completion failed schema validation (attempt %d/%d): %s",
                    attempt + 1,
                    MAX_RETRIES + 1,
                    exc,
                )
        logger.error("LLM completion exhausted retries, falling back: %s", last_error)
        return None


class NvidiaAdapter:
    """Talks to a DeepSeek model hosted on NVIDIA's NIM endpoint
    (integrate.api.nvidia.com), which is OpenAI-API-compatible -- so this
    uses the `openai` package with a custom base_url rather than a
    NVIDIA-specific SDK. A free-tier fallback alongside AnthropicAdapter.
    Requires the `openai` package and an API key; both are only ever
    needed here, never in core/."""

    def __init__(self, api_key: str, model: str = NVIDIA_PINNED_MODEL):
        from openai import OpenAI  # deferred: only llm/ needs this dependency at runtime

        self._client = OpenAI(api_key=api_key, base_url=NVIDIA_BASE_URL)
        self.model_string = model

    def complete(self, system: str, user: str, schema: type[T]) -> T | None:
        import openai  # deferred, same reason as above

        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self.model_string,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=TEMPERATURE,
                    max_tokens=MAX_TOKENS,
                    response_format={"type": "json_object"},
                    seed=42,
                    # Without this, a reasoning-capable DeepSeek variant can
                    # spend the output budget on chain-of-thought before
                    # writing any JSON, truncating the response -- these are
                    # short structured-output tasks, not reasoning tasks.
                    extra_body={"chat_template_kwargs": {"thinking": False}},
                )
                text = response.choices[0].message.content
                return _parse_response(text, schema)
            except (
                openai.APIError,
                ValidationError,
                json.JSONDecodeError,
                KeyError,
                AttributeError,
            ) as exc:
                last_error = exc
                logger.warning(
                    "NVIDIA/DeepSeek completion failed schema validation (attempt %d/%d): %s",
                    attempt + 1,
                    MAX_RETRIES + 1,
                    exc,
                )
        logger.error("NVIDIA/DeepSeek completion exhausted retries, falling back: %s", last_error)
        return None


def build_adapter(api_key: str | None, model: str = PINNED_MODEL) -> LLMAdapter:
    """Explicit Anthropic-only construction -- graceful degradation to
    NullAdapter when no key is present, never a crash."""
    if not api_key:
        return NullAdapter()
    return AnthropicAdapter(api_key=api_key, model=model)


def build_adapter_from_env() -> LLMAdapter:
    """The single place that decides which provider to use, so every
    caller (backend/services/reconcile_service.py, app/streamlit_app.py,
    evaluation/ablation.py) shares one policy instead of each hardcoding
    "read ANTHROPIC_API_KEY" itself. Checked in order: ANTHROPIC_API_KEY
    (the primary, most-tested path) -> NVIDIA_API_KEY (a free-tier
    fallback for testing without a paid key) -> NullAdapter, same graceful
    degradation as build_adapter().

    GeminiAdapter was removed: gemini-3.5-flash's free tier caps out at
    20 requests/day/project, confirmed live and trivially exhausted by a
    single `make eval` run -- unreliable enough in practice that it caused
    more problems than the free access was worth."""
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        return AnthropicAdapter(api_key=anthropic_key)
    nvidia_key = os.environ.get("NVIDIA_API_KEY")
    if nvidia_key:
        return NvidiaAdapter(api_key=nvidia_key)
    return NullAdapter()
