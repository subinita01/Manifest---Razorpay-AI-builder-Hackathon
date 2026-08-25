from decimal import Decimal

from core.matching.stage2_bridge import build_bridge

UTR = "1234567890123456"


def _payment_row(order_id, amount, fee, tax, on_hold=False):
    return {
        "settlement_id": f"setl_{order_id}",
        "settlement_utr": UTR,
        "type": "payment",
        "amount": Decimal(amount),
        "fee": Decimal(fee),
        "tax": Decimal(tax),
        "on_hold": on_hold,
        "order_id": order_id,
        "dispute_id": None,
    }


def _refund_row(order_id, amount):
    return {
        "settlement_id": f"setl_{order_id}_rf",
        "settlement_utr": UTR,
        "type": "refund",
        "amount": Decimal(amount),
        "fee": Decimal("0"),
        "tax": Decimal("0"),
        "on_hold": False,
        "order_id": order_id,
        "dispute_id": None,
    }


def _chargeback_row(order_id, amount):
    return {
        "settlement_id": f"setl_{order_id}_cb",
        "settlement_utr": UTR,
        "type": "adjustment",
        "amount": Decimal(amount),
        "fee": Decimal("0"),
        "tax": Decimal("0"),
        "on_hold": False,
        "order_id": order_id,
        "dispute_id": "disp_1",
    }


def test_clean_batch_closes_exactly():
    # 1000 gross, 2% MDR = 20.00, 18% GST on fee = 3.60 -> net = 976.40
    rows = [_payment_row("ord_1", "1000.00", "20.00", "3.60")]
    result = build_bridge(UTR, rows, bank_credit=Decimal("976.40"))
    assert result.closed is True
    assert result.residual == Decimal("0.00")
    assert result.attribution is None
    assert result.rate_variance is None
    assert result.steps[-1].running_total == Decimal("976.40")


def test_fee_variance_batch_is_flagged_with_implied_rate():
    # 2.4% MDR instead of the contracted 2%, but the bank credit reflects
    # what was actually charged, so the raw bridge still reconciles.
    gross = Decimal("10000.00")
    fee = Decimal("240.00")  # 2.4%
    tax = _round_gst(fee)
    rows = [_payment_row("ord_1", gross, fee, tax)]
    bank_credit = gross - fee - tax
    result = build_bridge(UTR, rows, bank_credit=bank_credit)
    assert result.closed is True
    assert result.rate_variance is not None
    assert result.rate_variance.rule == "FEE_VARIANCE"
    assert result.rate_variance.detail["implied_rate"] == "0.0240"


def test_gst_on_mdr_variance_batch_is_flagged():
    # 17% GST on the fee instead of the contracted 18%.
    gross = Decimal("10000.00")
    fee = Decimal("200.00")  # contracted 2%
    tax = Decimal("34.00")  # 17% of fee, not 18% (36.00)
    rows = [_payment_row("ord_1", gross, fee, tax)]
    bank_credit = gross - fee - tax
    result = build_bridge(UTR, rows, bank_credit=bank_credit)
    assert result.closed is True
    assert result.rate_variance is not None
    assert result.rate_variance.rule == "GST_ON_MDR_VARIANCE"
    assert result.rate_variance.detail["implied_rate"] == "0.1700"


def test_arbitrary_hole_stays_unattributed():
    gross = Decimal("10000.00")
    fee = Decimal("200.00")
    tax = Decimal("36.00")
    rows = [_payment_row("ord_1", gross, fee, tax)]
    expected_net = gross - fee - tax
    bank_credit = expected_net - Decimal("5000.00")
    result = build_bridge(UTR, rows, bank_credit=bank_credit)
    assert result.closed is False
    assert result.rate_variance is None
    assert result.attribution.rule == "UNATTRIBUTED"


def test_rounding_residual_within_bridge_tolerance_is_attributed():
    gross = Decimal("10000.00")
    fee = Decimal("200.00")
    tax = Decimal("36.00")
    rows = [_payment_row("ord_1", gross, fee, tax)]
    expected_net = gross - fee - tax
    bank_credit = expected_net + Decimal("0.07")
    result = build_bridge(UTR, rows, bank_credit=bank_credit)
    assert result.closed is False
    assert result.attribution.rule == "ROUNDING"


def test_refunds_chargebacks_and_on_hold_reduce_expected_net():
    rows = [
        _payment_row("ord_1", "1000.00", "20.00", "3.60"),
        _payment_row("ord_2", "500.00", "10.00", "1.80", on_hold=True),
        _refund_row("ord_1", "-100.00"),
        _chargeback_row("ord_1", "-50.00"),
    ]
    # ord_1 net: 1000 - 20 - 3.60 = 976.40; refund -100, chargeback -50 -> 826.40
    # ord_2 (on_hold): fully excluded from this cycle's net
    result = build_bridge(UTR, rows, bank_credit=Decimal("826.40"))
    assert result.closed is True
    labels = [s.label for s in result.steps]
    assert labels == [
        "Gross",
        "less MDR",
        "less GST",
        "less Refunds",
        "less Chargebacks",
        "less On-Hold",
    ]
    assert result.steps[0].amount == Decimal("1500.00")  # gross includes the held row


def _round_gst(fee: Decimal) -> Decimal:
    from decimal import ROUND_HALF_UP

    return (fee * Decimal("0.18")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
