from datetime import date, datetime
from decimal import Decimal

from core.matching.stage5_fuzzy import match_fuzzy

UTR_A = "9999888877776666"
UTR_B = "1111222233334444"


def _bank_row(row_id, credit, narration, txn_date=date(2026, 8, 14)):
    return {
        "row_id": row_id,
        "credit": Decimal(credit),
        "narration": narration,
        "txn_date": txn_date,
    }


def _settlement_group(utr, amount, fee, tax, settled_at=datetime(2026, 8, 14, 12, 0, 0)):
    return [
        {
            "settlement_id": f"setl_{utr}",
            "settlement_utr": utr,
            "type": "payment",
            "amount": Decimal(amount),
            "fee": Decimal(fee),
            "tax": Decimal(tax),
            "on_hold": False,
            "settled_at": settled_at,
            "order_id": f"ord_{utr}",
        }
    ]


def test_high_score_auto_matches():
    # narration carries the UTR as its own token -> token_set_ratio 100;
    # amount and date are exact -> total score 1.0.
    bank = [_bank_row(1, "976.40", f"SETTLEMENT UTR {UTR_A}")]
    settlement = _settlement_group(UTR_A, "1000.00", "20.00", "3.60")
    result = match_fuzzy(bank, settlement)
    assert len(result.matched) == 1
    assert result.matched[0].bank_row_id == "1"
    assert result.needs_review == []


def test_moderate_score_is_needs_review_not_a_match():
    # realistic hyphenated narration scores ~0.44 on narration_score; with
    # exact amount+date that lands the total in the 0.70-0.90 band.
    bank = [_bank_row(1, "976.40", f"NEFT CR-RAZORPAY SOFTWARE PVT LTD-UTR{UTR_A}-STL")]
    settlement = _settlement_group(UTR_A, "1000.00", "20.00", "3.60")
    result = match_fuzzy(bank, settlement)
    assert result.matched == []
    assert len(result.needs_review) == 1
    assert 0.70 <= result.needs_review[0].confidence < 0.90


def test_poor_score_stays_in_residue():
    bank = [_bank_row(1, "50000.00", "MISC BANK CHARGES", txn_date=date(2020, 1, 1))]
    settlement = _settlement_group(UTR_A, "1000.00", "20.00", "3.60")
    result = match_fuzzy(bank, settlement)
    assert result.matched == []
    assert result.needs_review == []
    assert len(result.residue_bank) == 1


def test_near_tie_is_ambiguous_not_matched():
    # two settlement groups with identical net and settled date; the bank
    # narration doesn't strongly favour either UTR, so their scores tie.
    bank = [_bank_row(1, "976.40", "UPI-SETTLEMENT-000000")]
    settlement = _settlement_group(UTR_A, "1000.00", "20.00", "3.60") + _settlement_group(
        UTR_B, "1000.00", "20.00", "3.60"
    )
    result = match_fuzzy(bank, settlement)
    assert result.matched == []
    assert result.needs_review == []
    assert len(result.ambiguous) == 1
    assert result.ambiguous[0]["reason"] == "fuzzy_near_tie"
