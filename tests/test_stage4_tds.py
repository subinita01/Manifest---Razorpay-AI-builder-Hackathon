import json
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from core.ingest import load_ledger_csv
from core.matching.stage4_tds import evaluate_tds

DEMO_DIR = Path(__file__).resolve().parent.parent / "data" / "demo"


def _row(**overrides):
    base = {
        "gross_amount": Decimal("10000.00"),
        "tds_section_legacy": None,
        "tds_code_new": None,
        "tds_amount": Decimal("0"),
        "vendor_pan_masked": "ABCP1234Z",
        "posted_at": datetime(2026, 5, 1),
    }
    base.update(overrides)
    return base


def test_no_tds_returns_none():
    assert evaluate_tds("ord_1", _row()) is None


def test_correct_tds_returns_none():
    row = _row(tds_code_new="1026", tds_amount=Decimal("1000.00"))
    assert evaluate_tds("ord_1", row) is None


def test_rule_a_migration_break():
    row = _row(
        posted_at=datetime(2026, 4, 15),
        tds_section_legacy="194J",
        tds_code_new=None,
        tds_amount=Decimal("1000.00"),
    )
    finding = evaluate_tds("ord_1", row)
    assert finding.rule_id == "TDS_RULE_A_MIGRATION_BREAK"
    assert finding.taxonomy_code == "TDS_CODE_MIGRATION_BREAK"
    assert finding.confidence == "config_dependent"
    assert finding.detail["suggested_code"] == "1026"
    assert finding.detail["config_file"] == "tds_code_map.yaml"
    assert finding.detail["verified"] is False


def test_rule_b_contradiction():
    row = _row(
        posted_at=datetime(2026, 4, 15),
        tds_section_legacy="194J",
        tds_code_new="1023",  # should be 1026 for 194J
        tds_amount=Decimal("1000.00"),
    )
    finding = evaluate_tds("ord_1", row)
    assert finding.rule_id == "TDS_RULE_B_CONTRADICTION"
    assert finding.taxonomy_code == "TDS_CODE_MIGRATION_BREAK"
    assert finding.confidence == "config_dependent"
    assert finding.detail["expected_new_code"] == "1026"
    assert finding.detail["recorded_new_code"] == "1023"


def test_rule_c_rate_mismatch_on_a_small_order():
    # implied rate far from scheduled rate, but the absolute delta stays
    # under Rs 1 so Rule D doesn't intercept it first.
    row = _row(gross_amount=Decimal("10.00"), tds_code_new="1026", tds_amount=Decimal("2.00"))
    finding = evaluate_tds("ord_1", row)
    assert finding.rule_id == "TDS_RULE_C_RATE_MISMATCH"
    assert finding.taxonomy_code == "TDS_RATE_MISMATCH"
    assert finding.detail["implied_rate"] == "0.2000"


def test_rule_d_amount_mismatch():
    row = _row(gross_amount=Decimal("10000.00"), tds_code_new="1026", tds_amount=Decimal("1005.00"))
    finding = evaluate_tds("ord_1", row)
    assert finding.rule_id == "TDS_RULE_D_AMOUNT_MISMATCH"
    assert finding.taxonomy_code == "TDS_AMOUNT_MISMATCH"
    assert finding.amount_impact == Decimal("5.00")
    assert finding.detail["expected_tds"] == "1000.00"


def test_rule_e_unknown_code():
    row = _row(tds_code_new="9999", tds_amount=Decimal("1000.00"))
    finding = evaluate_tds("ord_1", row)
    assert finding.rule_id == "TDS_RULE_E_UNKNOWN_CODE"
    assert finding.taxonomy_code == "TDS_RATE_MISMATCH"
    assert finding.confidence == "config_dependent"
    assert finding.detail["unknown_code"] == "9999"


def _load_ledger_rows():
    return {row["order_id"]: row for row in load_ledger_csv(DEMO_DIR / "internal_ledger.csv")}


def test_all_15_planted_tds_defects_are_detected_against_demo_data():
    ground_truth = json.loads((DEMO_DIR / "ground_truth.json").read_text())
    ledger_rows = _load_ledger_rows()

    tds_defects = [
        e
        for e in ground_truth["planted_exceptions"]
        if e["true_label"] in ("TDS_CODE_MIGRATION_BREAK", "TDS_AMOUNT_MISMATCH")
    ]
    assert len(tds_defects) == 15

    detected_labels = Counter()
    for defect in tds_defects:
        order_id = defect["order_ids"][0]
        finding = evaluate_tds(order_id, ledger_rows[order_id])
        assert finding is not None, f"{order_id} ({defect['true_label']}) was not flagged at all"
        assert finding.taxonomy_code == defect["true_label"], (
            f"{order_id}: expected {defect['true_label']}, got {finding.taxonomy_code} "
            f"via {finding.rule_id}"
        )
        detected_labels[finding.taxonomy_code] += 1

    assert detected_labels["TDS_CODE_MIGRATION_BREAK"] == 11
    assert detected_labels["TDS_AMOUNT_MISMATCH"] == 4
