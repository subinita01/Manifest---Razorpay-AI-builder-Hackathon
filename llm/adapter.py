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
GEMINI_PINNED_MODEL = "gemini-3.5-flash"  # on Google AI Studio's free tier
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


class GeminiAdapter:
    """Talks to the Google Gemini API. Free-tier friendly (see
    GEMINI_PINNED_MODEL) -- a way to exercise every llm/ code path without
    a paid Anthropic key. Requires the `google-genai` package and an API
    key; both are only ever needed here, never in core/."""

    def __init__(self, api_key: str, model: str = GEMINI_PINNED_MODEL):
        from google import genai  # deferred: only llm/ needs this dependency at runtime

        self._client = genai.Client(api_key=api_key)
        self.model_string = model

    def complete(self, system: str, user: str, schema: type[T]) -> T | None:
        from google.genai import errors, types  # deferred, same reason as above

        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = self._client.models.generate_content(
                    model=self.model_string,
                    contents=user,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        temperature=TEMPERATURE,
                        max_output_tokens=MAX_TOKENS,
                        response_mime_type="application/json",
                        # Without this, gemini-3.5-flash spends its output
                        # budget on internal reasoning before writing any
                        # JSON -- confirmed live: 982 of MAX_TOKENS=1024
                        # tokens went to thoughts_token_count, truncating
                        # the actual response mid-string on a real query
                        # over the full 45-exception demo run. These are
                        # short structured-output tasks; they don't need it.
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                    ),
                )
                return _parse_response(response.text, schema)
            except (
                errors.APIError,
                ValidationError,
                json.JSONDecodeError,
                KeyError,
                AttributeError,
            ) as exc:
                last_error = exc
                logger.warning(
                    "Gemini completion failed schema validation (attempt %d/%d): %s",
                    attempt + 1,
                    MAX_RETRIES + 1,
                    exc,
                )
        logger.error("Gemini completion exhausted retries, falling back: %s", last_error)
        return None


class NvidiaAdapter:
    """Talks to a DeepSeek model hosted on NVIDIA's NIM endpoint
    (integrate.api.nvidia.com), which is OpenAI-API-compatible -- so this
    uses the `openai` package with a custom base_url rather than a
    NVIDIA-specific SDK. A third free-tier option alongside GeminiAdapter.
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
                    # Same class of bug as Gemini's thinking_budget (see
                    # GeminiAdapter above): without this, a reasoning-capable
                    # DeepSeek variant can spend the output budget on
                    # chain-of-thought before writing any JSON. Disabled for
                    # the same reason -- these are short structured-output
                    # tasks, not reasoning tasks.
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
    (the primary, most-tested path) -> GEMINI_API_KEY -> NVIDIA_API_KEY
    (two free-tier fallbacks for testing without a paid key -- Gemini's
    free tier caps gemini-3.5-flash at 20 requests/day/project, confirmed
    live and easy to exhaust) -> NullAdapter, same graceful degradation
    as build_adapter()."""
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        return AnthropicAdapter(api_key=anthropic_key)
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        return GeminiAdapter(api_key=gemini_key)
    nvidia_key = os.environ.get("NVIDIA_API_KEY")
    if nvidia_key:
        return NvidiaAdapter(api_key=nvidia_key)
    return NullAdapter()
