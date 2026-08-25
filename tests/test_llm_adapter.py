from llm.adapter import NullAdapter, build_adapter
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
