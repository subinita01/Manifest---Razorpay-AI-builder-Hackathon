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
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger("manifest.llm")

T = TypeVar("T", bound=BaseModel)

TEMPERATURE = 0
MAX_TOKENS = 1024
PINNED_MODEL = "claude-sonnet-5"
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
                data = json.loads(text)
                return schema.model_validate(data)
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


def build_adapter(api_key: str | None, model: str = PINNED_MODEL) -> LLMAdapter:
    """The single place that decides which adapter to use -- graceful
    degradation to NullAdapter when no key is present, never a crash."""
    if not api_key:
        return NullAdapter()
    return AnthropicAdapter(api_key=api_key, model=model)
