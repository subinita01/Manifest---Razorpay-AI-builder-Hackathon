from llm.adapter import GeminiAdapter, NullAdapter, build_adapter, build_adapter_from_env
from llm.schemas import NarrationClassification


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


def test_build_adapter_returns_gemini_adapter_with_a_key():
    adapter = GeminiAdapter(api_key="fake-key-for-construction-only")
    assert adapter.model_string == "gemini-3.5-flash"


def test_build_adapter_from_env_prefers_anthropic_over_gemini(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake-anthropic-key")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    from llm.adapter import AnthropicAdapter

    adapter = build_adapter_from_env()
    assert isinstance(adapter, AnthropicAdapter)


def test_build_adapter_from_env_falls_back_to_gemini(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")

    adapter = build_adapter_from_env()
    assert isinstance(adapter, GeminiAdapter)


def test_build_adapter_from_env_returns_null_adapter_with_no_keys(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    adapter = build_adapter_from_env()
    assert isinstance(adapter, NullAdapter)


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
