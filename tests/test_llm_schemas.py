import pytest
from pydantic import ValidationError

from llm.schemas import AdjustmentDraft, NarrationClassification, NarrationType, RootCauseNarrative


def test_narration_classification_accepts_valid_payload():
    result = NarrationClassification(
        narration_type=NarrationType.SETTLEMENT,
        extracted_reference="123456",
        confidence=0.9,
        suspicious=False,
        reasoning="Matches known settlement narration pattern.",
    )
    assert result.narration_type == NarrationType.SETTLEMENT


def test_narration_classification_rejects_unknown_type():
    with pytest.raises(ValidationError):
        NarrationClassification(
            narration_type="NOT_A_REAL_TYPE",
            confidence=0.5,
            reasoning="x",
        )


def test_narration_classification_rejects_out_of_range_confidence():
    with pytest.raises(ValidationError):
        NarrationClassification(
            narration_type=NarrationType.OTHER,
            confidence=1.5,
            reasoning="x",
        )


def test_root_cause_narrative_rejects_extra_fields():
    with pytest.raises(ValidationError):
        RootCauseNarrative(
            explanation="x",
            suggested_action="y",
            confidence=0.5,
            unexpected_field="should not be allowed",
        )


def test_adjustment_draft_requires_at_least_one_line():
    with pytest.raises(ValidationError):
        AdjustmentDraft(lines=[], memo="empty")


def test_adjustment_draft_accepts_valid_payload():
    draft = AdjustmentDraft(
        lines=[{"account": "SUSPENSE_ACCOUNT", "dr": "100.00", "cr": "0.00"}],
        memo="Draft adjustment",
    )
    assert draft.lines[0].account == "SUSPENSE_ACCOUNT"
