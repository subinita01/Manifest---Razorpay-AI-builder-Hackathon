"""Stage 2: the gross-to-net settlement bridge.

For each settlement UTR-group, reconstructs the ordered waterfall

    Gross -> less MDR -> less GST -> less Refunds -> less Chargebacks
    -> less On-Hold -> expected_net

using each row's own recorded fee/tax, and compares expected_net to the
bank credit.

This module runs two independent checks per batch, because they answer
different questions:

  - Money reconciliation (`closed` / `residual` / `attribution`): does the
    settlement's own recorded figures actually add up to what hit the bank?
    A residual here means the bookkeeping itself doesn't add up (a data
    error, a rounding drift, or something unexplained).

  - Rate compliance (`rate_variance`): does the RECORDED fee/GST rate match
    the CONTRACTED rate from config? A settlement can reconcile perfectly
    (recorded fee = what hit the bank) while still being wrong relative to
    contract -- the merchant was charged 2.4% when the contract says 2%, and
    both the statement and the bank agree on the (wrong) 2.4%. That's a
    compliance finding, not a bookkeeping error, so it's checked regardless
    of whether the money side already closes.

`closed` means the RAW bridge reconciles to within TOLERANCE ("closes
exactly"), matching the product framing that only a clean, unattributed
zero counts as closed. Attribution (FEE_VARIANCE / GST_ON_MDR_VARIANCE /
ROUNDING / UNATTRIBUTED) is attempted in that order and stops at the first
explanation that brings the residual within BRIDGE_TOLERANCE (Rs 1.00) --
looser than TOLERANCE, which is why a bank-vs-batch match that Stage 1's
tight TOLERANCE rejected can still resolve here as ROUNDING.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from core.config import load_settings
from core.models import BRIDGE_TOLERANCE, TOLERANCE

CENT = Decimal("0.01")
RATE_VARIANCE_TOLERANCE = Decimal("0.001")


def _q(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _contracted_rates() -> tuple[Decimal, Decimal]:
    bridge_settings = load_settings()["bridge"]
    return Decimal(bridge_settings["mdr_rate"]), Decimal(bridge_settings["gst_on_mdr_rate"])


@dataclass
class BridgeStep:
    label: str
    amount: Decimal
    running_total: Decimal
    constituent_row_ids: list[str] = field(default_factory=list)


@dataclass
class BridgeFinding:
    rule: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class BridgeResult:
    settlement_utr: str
    steps: list[BridgeStep]
    expected_net: Decimal
    bank_credit: Decimal
    residual: Decimal
    closed: bool
    attribution: BridgeFinding | None = None
    rate_variance: BridgeFinding | None = None


def _rate_variance(
    active_rows: list[dict[str, Any]], mdr: Decimal, gst: Decimal
) -> BridgeFinding | None:
    contracted_mdr_rate, contracted_gst_rate = _contracted_rates()
    active_gross = sum((r["amount"] for r in active_rows), Decimal("0"))

    if active_gross > 0:
        implied_mdr_rate = (mdr / active_gross).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        if abs(implied_mdr_rate - contracted_mdr_rate) > RATE_VARIANCE_TOLERANCE:
            return BridgeFinding(
                "FEE_VARIANCE",
                {
                    "implied_rate": str(implied_mdr_rate),
                    "contracted_rate": str(contracted_mdr_rate),
                },
            )

    if mdr > 0:
        implied_gst_rate = (gst / mdr).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        if abs(implied_gst_rate - contracted_gst_rate) > RATE_VARIANCE_TOLERANCE:
            return BridgeFinding(
                "GST_ON_MDR_VARIANCE",
                {
                    "implied_rate": str(implied_gst_rate),
                    "contracted_rate": str(contracted_gst_rate),
                },
            )

    return None


def _attribute_residual(
    residual: Decimal,
    expected_net: Decimal,
    bank_credit: Decimal,
    active_rows: list[dict[str, Any]],
    mdr: Decimal,
    gst: Decimal,
) -> BridgeFinding:
    contracted_mdr_rate, contracted_gst_rate = _contracted_rates()
    active_gross = sum((r["amount"] for r in active_rows), Decimal("0"))

    # A rate-swap "explains" the residual only if the recorded rate actually
    # deviates from contract in the first place -- otherwise swapping to the
    # (identical) contracted rate is a no-op that would trivially "explain"
    # any unrelated residual under BRIDGE_TOLERANCE.
    if active_gross > 0:
        implied_mdr_rate = (mdr / active_gross).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        if abs(implied_mdr_rate - contracted_mdr_rate) > RATE_VARIANCE_TOLERANCE:
            contracted_mdr = _q(active_gross * contracted_mdr_rate)
            net_with_contracted_mdr = expected_net + mdr - contracted_mdr
            if abs(bank_credit - net_with_contracted_mdr) <= BRIDGE_TOLERANCE:
                return BridgeFinding("FEE_VARIANCE", {"implied_rate": str(implied_mdr_rate)})

    if mdr > 0:
        implied_gst_rate = (gst / mdr).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        if abs(implied_gst_rate - contracted_gst_rate) > RATE_VARIANCE_TOLERANCE:
            contracted_gst = _q(mdr * contracted_gst_rate)
            net_with_contracted_gst = expected_net + gst - contracted_gst
            if abs(bank_credit - net_with_contracted_gst) <= BRIDGE_TOLERANCE:
                return BridgeFinding("GST_ON_MDR_VARIANCE", {"implied_rate": str(implied_gst_rate)})

    if abs(residual) < BRIDGE_TOLERANCE:
        return BridgeFinding("ROUNDING", {"residual": str(residual)})

    return BridgeFinding("UNATTRIBUTED", {"residual": str(residual)})


def build_bridge(
    settlement_utr: str, rows: list[dict[str, Any]], bank_credit: Decimal
) -> BridgeResult:
    payment_rows = [r for r in rows if r["type"] == "payment"]
    active_rows = [r for r in payment_rows if not r["on_hold"]]
    held_rows = [r for r in payment_rows if r["on_hold"]]
    refund_rows = [r for r in rows if r["type"] == "refund"]
    chargeback_rows = [r for r in rows if r["type"] == "adjustment" and r.get("dispute_id")]

    gross = sum((r["amount"] for r in payment_rows), Decimal("0"))
    mdr = sum((r["fee"] for r in active_rows), Decimal("0"))
    gst = sum((r["tax"] for r in active_rows), Decimal("0"))
    refunds = sum((r["amount"] for r in refund_rows), Decimal("0"))
    chargebacks = sum((r["amount"] for r in chargeback_rows), Decimal("0"))
    on_hold_amount = sum((r["amount"] for r in held_rows), Decimal("0"))

    def ids(rows_subset: list[dict[str, Any]]) -> list[str]:
        return [r.get("settlement_id", "") for r in rows_subset]

    running = gross
    steps = [BridgeStep("Gross", gross, running, ids(payment_rows))]
    running -= mdr
    steps.append(BridgeStep("less MDR", -mdr, running, ids(active_rows)))
    running -= gst
    steps.append(BridgeStep("less GST", -gst, running, ids(active_rows)))
    running += refunds
    steps.append(BridgeStep("less Refunds", refunds, running, ids(refund_rows)))
    running += chargebacks
    steps.append(BridgeStep("less Chargebacks", chargebacks, running, ids(chargeback_rows)))
    running -= on_hold_amount
    steps.append(BridgeStep("less On-Hold", -on_hold_amount, running, ids(held_rows)))

    expected_net = running
    residual = bank_credit - expected_net
    closed = abs(residual) <= TOLERANCE

    attribution = None
    if not closed:
        attribution = _attribute_residual(
            residual, expected_net, bank_credit, active_rows, mdr, gst
        )

    rate_variance = _rate_variance(active_rows, mdr, gst)

    return BridgeResult(
        settlement_utr=settlement_utr,
        steps=steps,
        expected_net=expected_net,
        bank_credit=bank_credit,
        residual=residual,
        closed=closed,
        attribution=attribution,
        rate_variance=rate_variance,
    )
