from llm.adapter import NullAdapter
from llm.query import answer_question
from llm.schemas import QueryAnswer

EXCEPTIONS = [
    {
        "exception_id": "exc_1",
        "taxonomy_code": "UNEXPLAINED",
        "severity": "WARN",
        "amount_impact": "150.00",
        "row_ids": ["ord_001"],
        "detail": {},
    },
    {
        "exception_id": "exc_2",
        "taxonomy_code": "TDS_CODE_MIGRATION_BREAK",
        "severity": "CRITICAL",
        "amount_impact": "3658.78",
        "row_ids": ["ord_00251"],
        "detail": {},
    },
]


class _FakeAdapter:
    model_string = "fake"

    def __init__(self, response=None):
        self._response = response
        self.calls = []

    def complete(self, system, user, schema):
        self.calls.append((system, user, schema))
        return self._response


def test_answer_question_falls_back_on_null_adapter():
    result = answer_question(NullAdapter(), "why is ord_001 unexplained?", EXCEPTIONS)
    assert isinstance(result, QueryAnswer)
    assert "No LLM available" in result.answer
    assert result.cited_exception_ids == []


def test_answer_question_rejects_empty_question():
    result = answer_question(NullAdapter(), "   ", EXCEPTIONS)
    assert "Ask a question" in result.answer


def test_answer_question_rejects_no_exceptions():
    result = answer_question(NullAdapter(), "why is ord_001 unexplained?", [])
    assert "no exceptions" in result.answer.lower()


def test_answer_question_uses_adapter_result():
    fake = _FakeAdapter(
        response=QueryAnswer(
            answer="ord_001 is flagged because the bridge residual could not be attributed.",
            cited_exception_ids=["exc_1"],
        )
    )
    result = answer_question(fake, "why is ord_001 unexplained?", EXCEPTIONS)
    assert len(fake.calls) == 1
    assert result.cited_exception_ids == ["exc_1"]


def test_answer_question_drops_citations_for_exceptions_that_dont_exist():
    fake = _FakeAdapter(
        response=QueryAnswer(
            answer="Fabricated citation test.",
            cited_exception_ids=["exc_1", "exc_999_does_not_exist"],
        )
    )
    result = answer_question(fake, "summarize the exceptions", EXCEPTIONS)
    # The real citation survives; the invented one is dropped, not the whole answer.
    assert result.cited_exception_ids == ["exc_1"]
    assert result.answer == "Fabricated citation test."


def test_answer_question_truncates_a_pathologically_long_question():
    fake = _FakeAdapter(response=QueryAnswer(answer="ok"))
    long_question = "why? " * 200
    answer_question(fake, long_question, EXCEPTIONS)
    sent_user_payload = fake.calls[0][1]
    assert len(sent_user_payload) < len(long_question)
