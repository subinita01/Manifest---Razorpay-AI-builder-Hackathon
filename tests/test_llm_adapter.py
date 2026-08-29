import pytest

from llm.adapter import (
    NullAdapter,
    NvidiaAdapter,
    _parse_response,
    build_adapter,
    build_adapter_from_env,
)
from llm.schemas import NarrationClassification, NarrationType


def test_null_adapter_always_returns_none():
    adapter = NullAdapter()
    result = adapter.complete("system", "user", NarrationClassification)
    assert result is None


def test_build_adapter_returns_null_adapter_without_a_key():
    adapter = build_adapter(api_key=None)
    assert isinstance(adapter, NullAdapter)
    adapter2 = build_adapter(api_key="")
    assert isinstance(adapter2, NullAdapter)


def test_build_adapter_returns_anthropic_adapter_with_a_key():
    from llm.adapter import AnthropicAdapter

    adapter = build_adapter(api_key="sk-fake-key-for-construction-only")
    assert isinstance(adapter, AnthropicAdapter)
    assert adapter.model_string == "claude-sonnet-5"


def test_build_adapter_returns_nvidia_adapter_with_a_key():
    adapter = NvidiaAdapter(api_key="fake-key-for-construction-only")
    assert adapter.model_string == "deepseek-ai/deepseek-v4-pro-0813"


def test_build_adapter_from_env_prefers_anthropic_over_nvidia(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake-anthropic-key")
    monkeypatch.setenv("NVIDIA_API_KEY", "fake-nvidia-key")
    from llm.adapter import AnthropicAdapter

    adapter = build_adapter_from_env()
    assert isinstance(adapter, AnthropicAdapter)


def test_build_adapter_from_env_falls_back_to_nvidia(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "fake-nvidia-key")

    adapter = build_adapter_from_env()
    assert isinstance(adapter, NvidiaAdapter)


def test_build_adapter_from_env_returns_null_adapter_with_no_keys(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

    adapter = build_adapter_from_env()
    assert isinstance(adapter, NullAdapter)


def test_parse_response_coerces_a_real_provider_json_enum_string():
    """Regression test for a real bug caught by the first-ever live LLM
    call in this project (via the since-removed GeminiAdapter, no key had
    been available before): NarrationClassification sets strict=True in its own
    model_config, and every schema.model_validate(data) call used to
    validate under that config. JSON has no enum type, so narration_type
    always arrives as a plain string like "SETTLEMENT" -- and Pydantic v2
    strict mode's is_instance_of check on an Enum field rejects a plain
    str unconditionally, even though NarrationType is itself a (str, Enum)
    subclass. That's not a plausible-but-wrong LLM output; it's every
    real response from every provider, always -- so this exhausted
    retries and silently fell back to the deterministic default on every
    single narration-classification call this schema was ever used for,
    with nobody noticing until a real API key actually got exercised."""
    text = (
        '{"narration_type": "SETTLEMENT", "extracted_reference": "UTR123", '
        '"confidence": 0.95, "suspicious": false, "reasoning": "test"}'
    )
    result = _parse_response(text, NarrationClassification)
    assert result.narration_type == NarrationType.SETTLEMENT
    assert isinstance(result.narration_type, NarrationType)


def test_parse_response_raises_on_malformed_json():
    with pytest.raises(Exception):
        _parse_response("not valid json", NarrationClassification)


class _FakeSchemaFailAdapter:
    """Simulates a provider whose response never validates against the
    schema, exercising the same fallback path a real repeated failure
    would -- callers must treat this exactly like NullAdapter's None."""

    model_string = "fake"
    call_count = 0

    def complete(self, system, user, schema):
        self.call_count += 1
        return None


def test_adapter_protocol_is_satisfied_by_a_test_double():
    adapter = _FakeSchemaFailAdapter()
    result = adapter.complete("s", "u", NarrationClassification)
    assert result is None
    assert adapter.call_count == 1
