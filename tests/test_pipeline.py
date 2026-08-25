from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from core.ingest import load_bank_csv, load_ledger_csv, load_settlement_csv
from core.pipeline import InvariantViolation, run_pipeline

DEMO_DIR = Path(__file__).resolve().parent.parent / "data" / "demo"


def _clean_dataset():
    utr = "1234567890123456"
    bank_rows = [
        {
            "row_id": 0,
            "narration": f"NEFT CR-RAZORPAY SOFTWARE PVT LTD-UTR{utr}-STL",
            "credit": Decimal("976.40"),
            "txn_date": date(2026, 8, 14),
        }
    ]
    settlement_rows = [
        {
            "settlement_id": "setl_1",
            "settlement_utr": utr,
            "type": "payment",
            "amount": Decimal("1000.00"),
            "fee": Decimal("20.00"),
            "tax": Decimal("3.60"),
            "on_hold": False,
            "settled": True,
            "settled_at": datetime(2026, 8, 14, 12, 0, 0),
            "order_id": "ord_1",
            "dispute_id": None,
        }
    ]
    ledger_rows = [
        {
            "order_id": "ord_1",
            "gross_amount": Decimal("1000.00"),
            "tds_section_legacy": None,
            "tds_code_new": None,
            "tds_amount": Decimal("0"),
            "vendor_pan_masked": "ABCP1234Z",
            "posted_at": datetime(2026, 8, 14),
        }
    ]
    return bank_rows, settlement_rows, ledger_rows


def test_invariant_holds_on_a_clean_dataset():
    bank_rows, settlement_rows, ledger_rows = _clean_dataset()
    result = run_pipeline(bank_rows, settlement_rows, ledger_rows)
    assert result.total_input_rows == 3
    assert (
        result.matched_row_count + result.needs_review_row_count + result.exception_row_count == 3
    )
    assert result.exceptions == []


def test_run_result_retains_the_bridge_for_every_matched_batch():
    bank_rows, settlement_rows, ledger_rows = _clean_dataset()
    result = run_pipeline(bank_rows, settlement_rows, ledger_rows)
    assert "1234567890123456" in result.bridges
    assert result.bridges["1234567890123456"].closed is True


def test_invariant_fires_when_a_stage_silently_drops_a_row(monkeypatch):
    import core.pipeline as pipeline_module
    from core.matching.stage_result import StageResult

    def broken_match_utr(bank_rows, settlement_rows):
        # Simulate a stage that silently drops a bank row: it appears in
        # neither matched nor residue_bank.
        return StageResult(stage_name="stage1_utr")

    monkeypatch.setattr(pipeline_module, "match_utr", broken_match_utr)

    bank_rows, settlement_rows, ledger_rows = _clean_dataset()
    with pytest.raises(InvariantViolation):
        run_pipeline(bank_rows, settlement_rows, ledger_rows)


def test_ledger_only_order_is_an_exception_not_silently_dropped():
    bank_rows, settlement_rows, ledger_rows = _clean_dataset()
    # Add an order that's in the ledger but never settled.
    ledger_rows.append(
        {
            "order_id": "ord_orphan",
            "gross_amount": Decimal("500.00"),
            "tds_section_legacy": None,
            "tds_code_new": None,
            "tds_amount": Decimal("0"),
            "vendor_pan_masked": "ABCP9999Z",
            "posted_at": datetime(2026, 8, 14),
        }
    )
    result = run_pipeline(bank_rows, settlement_rows, ledger_rows)
    assert result.total_input_rows == 4
    assert (
        result.matched_row_count + result.needs_review_row_count + result.exception_row_count == 4
    )
    codes = [e.taxonomy_code for e in result.exceptions]
    assert "LEDGER_ONLY" in codes


def test_gate_6_full_pipeline_against_demo_dataset():
    """GATE 6: full deterministic pipeline runs end to end on demo data,
    the invariant holds, and UNEXPLAINED >= 3 (a 100% match rate with zero
    unexplained exceptions is a failure state, not a success)."""
    bank_rows = load_bank_csv(DEMO_DIR / "bank_statement.csv")
    settlement_rows = load_settlement_csv(DEMO_DIR / "settlement_batch.csv")
    ledger_rows = load_ledger_csv(DEMO_DIR / "internal_ledger.csv")

    result = run_pipeline(bank_rows, settlement_rows, ledger_rows)

    assert (
        result.matched_row_count + result.needs_review_row_count + result.exception_row_count
        == result.total_input_rows
    )

    counts = Counter(e.taxonomy_code for e in result.exceptions)
    assert counts["UNEXPLAINED"] >= 3
    assert counts["TDS_CODE_MIGRATION_BREAK"] == 11
    assert counts["TDS_AMOUNT_MISMATCH"] == 4
    assert counts["FEE_VARIANCE"] == 3
    assert counts["GST_ON_MDR_VARIANCE"] == 2
