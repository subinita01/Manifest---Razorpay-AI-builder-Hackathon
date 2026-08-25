from decimal import Decimal

from core.matching.stage2_bridge import BridgeFinding, BridgeResult
from core.matching.stage4_tds import TDSFinding
from core.matching.stage6_classify import (
    classify_ambiguous,
    classify_bank_only,
    classify_bridge_result,
    classify_ledger_only,
    classify_settlement_only,
    classify_tds_finding,
)


def test_classify_bank_only():
    rows = [{"row_id": 5, "credit": Decimal("100.00"), "narration": "MYSTERY"}]
    exceptions = classify_bank_only(rows)
    assert len(exceptions) == 1
    assert exceptions[0].taxonomy_code == "BANK_ONLY"
    assert exceptions[0].severity == "WARN"
    assert exceptions[0].amount_impact == Decimal("100.00")


def test_classify_ledger_only():
    rows = [{"order_id": "ord_1", "gross_amount": Decimal("500.00")}]
    exceptions = classify_ledger_only(rows)
    assert exceptions[0].taxonomy_code == "LEDGER_ONLY"
    assert exceptions[0].row_ids == ["ord_1"]


def test_classify_settlement_only():
    rows = [{"settlement_id": "setl_1", "amount": Decimal("200.00"), "order_id": "ord_1"}]
    exceptions = classify_settlement_only(rows)
    assert exceptions[0].taxonomy_code == "SETTLEMENT_ONLY"


def test_classify_ambiguous():
    entries = [{"bank_row_id": 7, "reason": "fuzzy_near_tie"}]
    exceptions = classify_ambiguous(entries)
    assert exceptions[0].taxonomy_code == "AMBIGUOUS_MATCH"


def test_classify_bridge_result_rate_variance_takes_priority():
    bridge = BridgeResult(
        settlement_utr="utr1",
        steps=[],
        expected_net=Decimal("100.00"),
        bank_credit=Decimal("100.00"),
        residual=Decimal("0.00"),
        closed=True,
        attribution=None,
        rate_variance=BridgeFinding("FEE_VARIANCE", {"implied_rate": "0.0240"}),
    )
    exc = classify_bridge_result(bridge)
    assert exc.taxonomy_code == "FEE_VARIANCE"


def test_classify_bridge_result_unattributed_becomes_unexplained():
    bridge = BridgeResult(
        settlement_utr="utr1",
        steps=[],
        expected_net=Decimal("100.00"),
        bank_credit=Decimal("5100.00"),
        residual=Decimal("5000.00"),
        closed=False,
        attribution=BridgeFinding("UNATTRIBUTED", {"residual": "5000.00"}),
        rate_variance=None,
    )
    exc = classify_bridge_result(bridge)
    assert exc.taxonomy_code == "UNEXPLAINED"
    assert exc.severity == "CRITICAL"


def test_classify_bridge_result_clean_returns_none():
    bridge = BridgeResult(
        settlement_utr="utr1",
        steps=[],
        expected_net=Decimal("100.00"),
        bank_credit=Decimal("100.00"),
        residual=Decimal("0.00"),
        closed=True,
        attribution=None,
        rate_variance=None,
    )
    assert classify_bridge_result(bridge) is None


def test_classify_tds_finding():
    finding = TDSFinding(
        rule_id="TDS_RULE_D_AMOUNT_MISMATCH",
        taxonomy_code="TDS_AMOUNT_MISMATCH",
        amount_impact=Decimal("5.00"),
        confidence="high",
        detail={"expected_tds": "100.00", "actual_tds": "105.00"},
    )
    exc = classify_tds_finding("ord_1", finding)
    assert exc.taxonomy_code == "TDS_AMOUNT_MISMATCH"
    assert exc.row_ids == ["ord_1"]
    assert exc.detail["rule_id"] == "TDS_RULE_D_AMOUNT_MISMATCH"
