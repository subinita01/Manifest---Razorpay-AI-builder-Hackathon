from decimal import Decimal

from core.models import Exception_, MatchResult
from core.pipeline import RunResult
from llm.adapter import NullAdapter
from llm.enrich import enrich_run_result


def _sample_result() -> RunResult:
    return RunResult(
        matched=[
            MatchResult(
                match_id="m1", stage_name="stage1_utr", bank_row_id="0", settlement_row_id="utr1"
            )
        ],
        needs_review=[],
        exceptions=[
            Exception_(
                exception_id="exc1",
                taxonomy_code="BANK_ONLY",
                severity="WARN",
                row_ids=["3"],
                amount_impact=Decimal("500.00"),
                detail={"bank_row_id": 3, "narration": "MYSTERY CREDIT NO REF"},
            )
        ],
        total_input_rows=2,
        matched_row_count=1,
        needs_review_row_count=0,
        exception_row_count=1,
    )


def test_enrich_adds_advisory_annotations_without_touching_core_fields():
    result = _sample_result()
    original_taxonomy = result.exceptions[0].taxonomy_code
    original_row_ids = list(result.exceptions[0].row_ids)
    original_amount = result.exceptions[0].amount_impact

    enriched = enrich_run_result(result, NullAdapter(), {3: "MYSTERY CREDIT NO REF"})

    exc = enriched.exceptions[0]
    assert exc.taxonomy_code == original_taxonomy
    assert exc.row_ids == original_row_ids
    assert exc.amount_impact == original_amount
    assert "llm_narration_classification" in exc.detail
    assert "llm_root_cause" in exc.detail
    assert "llm_adjustment_draft" in exc.detail


def test_enrich_does_not_change_matched_needs_review_or_exception_counts():
    result = _sample_result()
    enrich_run_result(result, NullAdapter(), {3: "MYSTERY CREDIT NO REF"})
    assert len(result.matched) == 1
    assert len(result.needs_review) == 0
    assert len(result.exceptions) == 1
    assert result.matched_row_count == 1
    assert result.needs_review_row_count == 0
    assert result.exception_row_count == 1


def test_enrich_skips_narration_classification_when_extract_utr_succeeds():
    result = _sample_result()
    # A narration extract_utr *can* parse -- job 1 should not run for this row.
    good_narration = "NEFT CR-RAZORPAY SOFTWARE PVT LTD-UTR2026081412345-STL"
    enrich_run_result(result, NullAdapter(), {3: good_narration})
    assert "llm_narration_classification" not in result.exceptions[0].detail
    # Jobs 2 and 3 still run regardless.
    assert "llm_root_cause" in result.exceptions[0].detail
