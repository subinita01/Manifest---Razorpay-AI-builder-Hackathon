from decimal import Decimal

from core.matching.stage3_order import match_order


def _settlement_row(settlement_id, order_id, amount):
    return {
        "settlement_id": settlement_id,
        "order_id": order_id,
        "amount": Decimal(amount),
        "type": "payment",
    }


def _ledger_row(order_id, gross_amount):
    return {"order_id": order_id, "gross_amount": Decimal(gross_amount)}


def test_matches_settlement_to_ledger_on_order_id():
    settlement = [_settlement_row("setl_1", "ord_1", "1000.00")]
    ledger = [_ledger_row("ord_1", "1000.00")]
    result = match_order(settlement, ledger)
    assert len(result.matched) == 1
    assert result.matched[0].ledger_row_id == "ord_1"
    assert result.residue_settlement == []
    assert result.residue_ledger == []


def test_amount_mismatch_beyond_tolerance_does_not_match():
    settlement = [_settlement_row("setl_1", "ord_1", "1000.00")]
    ledger = [_ledger_row("ord_1", "1050.00")]
    result = match_order(settlement, ledger)
    assert result.matched == []
    assert len(result.residue_settlement) == 1
    assert len(result.residue_ledger) == 1


def test_settlement_only_when_no_ledger_row_exists():
    settlement = [_settlement_row("setl_1", "ord_1", "1000.00")]
    ledger: list[dict] = []
    result = match_order(settlement, ledger)
    assert result.matched == []
    assert len(result.residue_settlement) == 1
    assert result.residue_ledger == []


def test_ledger_only_when_no_settlement_row_exists():
    settlement: list[dict] = []
    ledger = [_ledger_row("ord_1", "1000.00")]
    result = match_order(settlement, ledger)
    assert result.matched == []
    assert result.residue_settlement == []
    assert len(result.residue_ledger) == 1
