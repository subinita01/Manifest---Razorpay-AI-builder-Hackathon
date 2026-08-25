from datetime import date, datetime
from decimal import Decimal

from core.matching.stage1_utr import match_utr

UTR = "2026081412345"


def _bank_row(row_id, credit, narration=None, txn_date=date(2026, 8, 14)):
    return {
        "row_id": row_id,
        "narration": narration or f"NEFT CR-RAZORPAY SOFTWARE PVT LTD-UTR{UTR}-STL",
        "credit": Decimal(credit),
        "txn_date": txn_date,
    }


def _settlement_row(settlement_id, amount, fee, tax, utr=UTR, settled_at=None, on_hold=False):
    return {
        "settlement_id": settlement_id,
        "settlement_utr": utr,
        "amount": Decimal(amount),
        "fee": Decimal(fee),
        "tax": Decimal(tax),
        "on_hold": on_hold,
        "type": "payment",
        "settled_at": settled_at or datetime(2026, 8, 14, 12, 0, 0),
        "order_id": f"ord_{settlement_id}",
    }


def test_exact_match():
    bank = [_bank_row(1, "970.00")]
    settlement = [_settlement_row("s1", "1000.00", "20.00", "10.00")]
    result = match_utr(bank, settlement)
    assert len(result.matched) == 1
    assert result.matched[0].bank_row_id == "1"
    assert result.residue_bank == []
    assert result.residue_settlement == []


def test_amount_off_by_small_margin_does_not_match():
    bank = [_bank_row(1, "970.02")]
    settlement = [_settlement_row("s1", "1000.00", "20.00", "10.00")]
    result = match_utr(bank, settlement)
    assert result.matched == []
    assert len(result.residue_bank) == 1
    assert len(result.residue_settlement) == 1


def test_date_off_by_three_days_does_not_match():
    bank = [_bank_row(1, "970.00", txn_date=date(2026, 8, 17))]
    settlement = [_settlement_row("s1", "1000.00", "20.00", "10.00")]
    result = match_utr(bank, settlement)
    assert result.matched == []
    assert len(result.residue_bank) == 1


def test_duplicate_utr_claimed_by_two_bank_rows_is_ambiguous_not_matched():
    bank = [_bank_row(1, "970.00"), _bank_row(2, "970.00")]
    settlement = [_settlement_row("s1", "1000.00", "20.00", "10.00")]
    result = match_utr(bank, settlement)
    assert result.matched == []
    assert len(result.ambiguous) == 2
    assert len(result.residue_bank) == 2
