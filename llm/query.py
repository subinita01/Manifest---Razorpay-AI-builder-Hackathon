"""On-demand natural-language Q&A over an already-computed run's
exceptions. Unlike llm/enrich.py's eager, per-exception jobs, this runs
live, on request, from the UI -- a user types a question, gets an answer.

Structurally advisory, same as every other job in this package: it only
ever returns text for display, never mutates a RunResult, an exception,
or anything persisted, so it's incapable of altering a match decision
(CLAUDE.md rule 3) no matter what it answers. Never called from
core/pipeline.py or llm/enrich.py.
"""

from __future__ import annotations

from typing import Any

from llm.adapter import LLMAdapter
from llm.prompts import query_prompt
from llm.schemas import QueryAnswer

MAX_QUESTION_LENGTH = 300
# Generous relative to a single run's realistic exception count (the demo
# dataset has 45); a run with more than this would need retrieval instead
# of "paste every exception into the prompt," which is out of scope here.
MAX_EXCEPTIONS_IN_CONTEXT = 200


def fallback_answer() -> QueryAnswer:
    return QueryAnswer(
        answer=(
            "No LLM available to answer this question (no API key configured, or the "
            "request failed). Use the taxonomy/severity filters above to browse "
            "exceptions directly."
        ),
        cited_exception_ids=[],
    )


def _summarize(exceptions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "exception_id": e["exception_id"],
            "taxonomy_code": e["taxonomy_code"],
            "severity": e["severity"],
            "amount_impact": e["amount_impact"],
            "row_ids": e["row_ids"],
        }
        for e in exceptions[:MAX_EXCEPTIONS_IN_CONTEXT]
    ]


def answer_question(
    adapter: LLMAdapter, question: str, exceptions: list[dict[str, Any]]
) -> QueryAnswer:
    question = question.strip()[:MAX_QUESTION_LENGTH]
    if not question:
        return QueryAnswer(answer="Ask a question about this run's exceptions first.")
    if not exceptions:
        return QueryAnswer(answer="This run has no exceptions to ask about.")

    system, user = query_prompt(question, _summarize(exceptions))
    result = adapter.complete(system, user, QueryAnswer)
    if result is None:
        return fallback_answer()

    # Schema validation can't check that a cited ID actually exists in this
    # run -- drop any the model invented rather than discard an otherwise
    # useful answer over a bad citation.
    real_ids = {e["exception_id"] for e in exceptions}
    valid_citations = [cid for cid in result.cited_exception_ids if cid in real_ids]
    if valid_citations != result.cited_exception_ids:
        return QueryAnswer(answer=result.answer, cited_exception_ids=valid_citations)
    return result
