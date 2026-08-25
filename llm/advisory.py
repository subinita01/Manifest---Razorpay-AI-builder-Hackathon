"""LLM advisory jobs: narration classification, root-cause narrative, and
adjustment drafting. Every job calls its adapter, validates the response
(the adapter itself already does this -- see llm/adapter.py), and falls
back to a deterministic default when the adapter returns None (no key,
provider error, or schema validation failed twice). CLAUDE.md rule 3:
nothing here can create, clear, or alter a match decision -- these
functions only ever produce advisory annotations a caller attaches to an
exception's `detail` dict.
"""

from __future__ import annotations

import re

from core.config import load_chart_of_accounts
from llm.adapter import LLMAdapter
from llm.prompts import adjustment_draft_prompt, narration_classification_prompt, root_cause_prompt
from llm.schemas import AdjustmentDraft, NarrationClassification, NarrationType, RootCauseNarrative

# Deterministic first line of defense against prompt injection, independent
# of whether an LLM is even available: a narration matching one of these
# patterns is flagged SUSPICIOUS by the fallback path too, not just by the
# LLM's own judgment. Defense in depth (see llm/prompts.py's docstring).
_SUSPICIOUS_PATTERNS = re.compile(
    r"ignore (all |the )?(previous|prior|above) instructions"
    r"|disregard (all |the )?(previous|prior|above)"
    r"|you are now"
    r"|new instructions?:"
    r"|system prompt"
    r"|mark (all|this|these) (rows?|records?|transactions?) as matched"
    r"|act as (if|a)",
    re.IGNORECASE,
)


def _looks_suspicious(narration: str) -> bool:
    return bool(_SUSPICIOUS_PATTERNS.search(narration))


def fallback_narration_classification(narration: str) -> NarrationClassification:
    suspicious = _looks_suspicious(narration)
    return NarrationClassification(
        narration_type=NarrationType.SUSPICIOUS if suspicious else NarrationType.OTHER,
        extracted_reference=None,
        confidence=0.0,
        suspicious=suspicious,
        reasoning=(
            "Deterministic fallback: matched a known prompt-injection pattern."
            if suspicious
            else "Deterministic fallback: no LLM classification available."
        ),
    )


def fallback_root_cause(taxonomy_code: str) -> RootCauseNarrative:
    return RootCauseNarrative(
        explanation=f"No LLM narrative available for this {taxonomy_code} exception.",
        suggested_action="Manual review required.",
        confidence=0.0,
    )


def fallback_adjustment_draft() -> AdjustmentDraft:
    return AdjustmentDraft(
        lines=[{"account": "SUSPENSE_ACCOUNT", "dr": "0.00", "cr": "0.00"}],
        memo="Deterministic fallback; no LLM adjustment generated.",
    )


def classify_narration(adapter: LLMAdapter, narration: str) -> NarrationClassification:
    """Called only when the regex extractor (core.normalize.extract_utr)
    returned None -- there's nothing for an LLM to usefully add on a
    narration the deterministic extractor already parsed successfully."""
    if _looks_suspicious(narration):
        # Never even send an obviously-injected payload to the model; the
        # deterministic classification is already correct and cheaper.
        return fallback_narration_classification(narration)
    system, user = narration_classification_prompt(narration)
    result = adapter.complete(system, user, NarrationClassification)
    if result is None:
        return fallback_narration_classification(narration)
    return result


def generate_root_cause(
    adapter: LLMAdapter, taxonomy_code: str, pruned_detail: dict
) -> RootCauseNarrative:
    system, user = root_cause_prompt(taxonomy_code, pruned_detail)
    result = adapter.complete(system, user, RootCauseNarrative)
    if result is None:
        return fallback_root_cause(taxonomy_code)
    return result


def generate_adjustment_draft(
    adapter: LLMAdapter, taxonomy_code: str, amount_impact: str
) -> AdjustmentDraft:
    chart_of_accounts = load_chart_of_accounts()
    system, user = adjustment_draft_prompt(taxonomy_code, amount_impact, chart_of_accounts)
    result = adapter.complete(system, user, AdjustmentDraft)
    if result is None:
        return fallback_adjustment_draft()
    # Even a schema-valid response could name an account outside the chart
    # (the schema can't enforce that itself); reject and fall back rather
    # than persist a draft against a nonexistent account.
    if any(line.account not in chart_of_accounts for line in result.lines):
        return fallback_adjustment_draft()
    return result
