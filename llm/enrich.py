"""Optional post-processing: enrich a RunResult's exceptions with LLM
advisory annotations. Never called from core/pipeline.py -- core/ has
already made every match decision by the time this runs, and nothing here
can revise them (CLAUDE.md rule 3). Safe to skip entirely (use_llm=False),
and this is exactly what GATE 9 tests: a pipeline result must be
byte-identical whether or not this function is ever called.
"""

from __future__ import annotations

from typing import Any

from core.normalize import extract_utr
from core.pipeline import RunResult
from llm.adapter import LLMAdapter
from llm.advisory import classify_narration, generate_adjustment_draft, generate_root_cause
from llm.prompts import prune_fields


def enrich_run_result(
    result: RunResult,
    adapter: LLMAdapter,
    bank_narration_by_row_id: dict[Any, str],
) -> RunResult:
    """Mutates and returns `result`: only ever adds keys under each
    exception's `detail` dict (llm_narration_classification, llm_root_cause,
    llm_adjustment_draft). Never touches taxonomy_code, severity, row_ids,
    or amount_impact, and never adds to or removes from result.matched,
    result.needs_review, or result.exceptions.

    Note for a real deployment with a paid API key: this calls the LLM up
    to 3 times per exception. For a large exception count that's a real
    cost/latency choice -- fine for a hackathon demo scale, but a
    production version would likely make this on-demand per row instead
    of eager for every exception in a run.
    """
    for exc in result.exceptions:
        # Job 1: narration classification, only when the deterministic
        # extractor found nothing to work with.
        bank_row_id = exc.detail.get("bank_row_id")
        if bank_row_id is not None:
            narration = bank_narration_by_row_id.get(bank_row_id)
            if narration is not None and extract_utr(narration) is None:
                classification = classify_narration(adapter, narration)
                exc.detail["llm_narration_classification"] = classification.model_dump(mode="json")

        # Job 2: root-cause narrative, on a pruned, size-bounded view of detail.
        source_fields = {k: v for k, v in exc.detail.items() if not k.startswith("llm_")}
        narrative = generate_root_cause(adapter, exc.taxonomy_code, prune_fields(source_fields))
        exc.detail["llm_root_cause"] = narrative.model_dump(mode="json")

        # Job 3: adjustment draft.
        draft = generate_adjustment_draft(adapter, exc.taxonomy_code, str(exc.amount_impact))
        exc.detail["llm_adjustment_draft"] = draft.model_dump(mode="json")

    return result
