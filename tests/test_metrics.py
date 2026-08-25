import json
from decimal import Decimal
from pathlib import Path

from core.ingest import load_bank_csv, load_ledger_csv, load_settlement_csv
from core.models import Exception_, MatchResult
from core.pipeline import RunResult, run_pipeline
from evaluation.metrics import evaluate_run

DEMO_DIR = Path(__file__).resolve().parent.parent / "data" / "demo"


def test_correct_match_yields_full_precision_and_recall():
    ground_truth = {
        "expected_matches": [
            {"bank_row_id": 0, "order_ids": [], "settlement_ids": [], "settlement_utr": "utr1"}
        ],
        "planted_exceptions": [],
        "unresolvable_by_design": [],
    }
    result = RunResult(
        matched=[
            MatchResult(
                match_id="m1", stage_name="stage1_utr", bank_row_id="0", settlement_row_id="utr1"
            )
        ],
    )
    report = evaluate_run(
        result,
        ground_truth,
        n_bank_rows=1,
        bank_credit_by_row={0: Decimal("100.00")},
        settlement_utr_by_id={},
    )
    assert report.matcher_precision == 1.0
    assert report.matcher_recall == 1.0
    assert report.false_positive_cost_inr == Decimal("0")


def test_wrong_match_costs_the_bank_credit_as_false_positive():
    ground_truth = {
        "expected_matches": [
            {"bank_row_id": 0, "order_ids": [], "settlement_ids": [], "settlement_utr": "utr1"}
        ],
        "planted_exceptions": [],
        "unresolvable_by_design": [],
    }
    result = RunResult(
        matched=[
            MatchResult(
                match_id="m1",
                stage_name="stage1_utr",
                bank_row_id="0",
                settlement_row_id="wrong_utr",
            )
        ],
    )
    report = evaluate_run(
        result,
        ground_truth,
        n_bank_rows=1,
        bank_credit_by_row={0: Decimal("250.00")},
        settlement_utr_by_id={},
    )
    assert report.matcher_precision == 0.0
    assert report.false_positive_cost_inr == Decimal("250.00")


def test_flagged_but_correct_match_is_still_counted_correct():
    # FEE_VARIANCE batches are matched AND flagged at once -- the matching
    # decision itself is right, so precision must not be penalized for it.
    ground_truth = {
        "expected_matches": [],
        "planted_exceptions": [
            {
                "true_label": "FEE_VARIANCE",
                "bank_row_id": 0,
                "settlement_ids": ["setl_1"],
                "order_ids": [],
                "amount_impact": "10.00",
                "detail": "implied_rate=0.024",
            }
        ],
        "unresolvable_by_design": [],
    }
    result = RunResult(
        matched=[
            MatchResult(
                match_id="m1", stage_name="stage1_utr", bank_row_id="0", settlement_row_id="utr1"
            )
        ],
        exceptions=[
            Exception_(
                exception_id="exc1",
                taxonomy_code="FEE_VARIANCE",
                severity="WARN",
                row_ids=["setl_1"],
                amount_impact=Decimal("10.00"),
                detail={"settlement_utr": "utr1"},
            )
        ],
    )
    report = evaluate_run(
        result,
        ground_truth,
        n_bank_rows=1,
        bank_credit_by_row={0: Decimal("500.00")},
        settlement_utr_by_id={"setl_1": "utr1"},
    )
    assert report.matcher_precision == 1.0
    assert report.matcher_recall == 1.0
    assert report.false_positive_cost_inr == Decimal("0")


def test_unresolvable_by_design_scored_by_punt_not_taxonomy_match():
    ground_truth = {
        "expected_matches": [],
        "planted_exceptions": [],
        "unresolvable_by_design": [
            {"id": "u1", "bank_row_id": 0, "candidate_settlement_utrs": ["a", "b"]}
        ],
    }
    result = RunResult(
        exceptions=[
            Exception_(
                exception_id="exc1",
                taxonomy_code="AMBIGUOUS_MATCH",
                severity="WARN",
                row_ids=["0"],
                amount_impact=Decimal("0"),
                detail={"bank_row_id": 0},
            )
        ],
    )
    report = evaluate_run(
        result, ground_truth, n_bank_rows=1, bank_credit_by_row={}, settlement_utr_by_id={}
    )
    assert report.unresolvable_by_design_detection_rate == 1.0
    # Excluded from the taxonomy macro-F1 -- it has no single correct code.
    assert "UNRESOLVABLE_BY_DESIGN" not in report.exception_per_class


def test_gate_7_metrics_are_sane_against_demo_dataset():
    bank_rows = load_bank_csv(DEMO_DIR / "bank_statement.csv")
    settlement_rows = load_settlement_csv(DEMO_DIR / "settlement_batch.csv")
    ledger_rows = load_ledger_csv(DEMO_DIR / "internal_ledger.csv")
    ground_truth = json.loads((DEMO_DIR / "ground_truth.json").read_text())

    result = run_pipeline(bank_rows, settlement_rows, ledger_rows)
    bank_credit_by_row = {r["row_id"]: r["credit"] for r in bank_rows}
    settlement_utr_by_id = {r["settlement_id"]: r["settlement_utr"] for r in settlement_rows}

    report = evaluate_run(
        result, ground_truth, len(bank_rows), bank_credit_by_row, settlement_utr_by_id
    )

    # The line this product must never cross: reporting a match rate that
    # isn't measured against ground truth, or a suspiciously perfect one.
    assert 0.0 < report.auto_match_rate < 1.0
    assert report.matcher_precision == 1.0  # no false positives on this dataset
    assert report.matcher_recall < 1.0  # TIMING_T_PLUS_N is a known, real gap
    assert report.unresolvable_by_design_detection_rate == 1.0
    assert report.exception_per_class["TIMING_T_PLUS_N"].recall == 0.0
