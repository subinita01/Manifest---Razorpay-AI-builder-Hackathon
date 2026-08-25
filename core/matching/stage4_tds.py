"""Stage 4: TDS code-migration and amount validation.

Runs against ledger rows already matched in Stage 3 that carry TDS. Rules
fire in order and stop at the first one that matches -- an order gets
exactly one TDS finding, never several competing ones:

  A. migration break: posted on/after the cutover, legacy section present,
     new code missing.
  B. contradiction: both codes present but the map disagrees.
  (code resolution: if neither A nor B fired but the resolved code isn't in
   the rate schedule at all, that's rule E.)
  D. amount: recomputed TDS (gross * scheduled rate) differs from the
     recorded tds_amount by more than Rs 1.00.
  C. rate: the *implied* rate (tds_amount / gross_amount) differs from the
     scheduled rate by more than 0.001.

D is checked before C, reversing the build plan's literal C-then-D order.
Reason: a fixed rupee-level drift (a posting/rounding slip) produces a
*relative* deviation that can exceed the 0.001 rate tolerance on a small
order even though nothing about the rate is wrong -- confirmed against this
project's own demo data, where a ~Rs 5 drift on a ~Rs 6,600 order deviates
by 0.0011, just over the C threshold. Checking the Rs 1 materiality floor
first means a small absolute drift is classified as an amount problem
(matching what it actually is), and the stricter relative check is reserved
for cases the absolute floor doesn't already explain -- which in practice
means small orders where even a small absolute slip represents a real,
proportionally large rate error.

Because config/tds_code_map.yaml is unverified (see its header), every
finding from Rules A and B sets confidence="config_dependent" and names the
config file and its verified flag in the detail payload -- the uncertainty
is visible in the product, not hidden in a slide.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from core.config import UnknownTDSCodeError, lookup_new_code, lookup_rate

RATE_TOLERANCE = Decimal("0.001")
AMOUNT_TOLERANCE = Decimal("1.00")
CODE_MAP_FILENAME = "tds_code_map.yaml"
TDS_CUTOVER = datetime(2026, 4, 1)


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class TDSFinding:
    rule_id: str
    taxonomy_code: str
    amount_impact: Decimal
    confidence: str
    detail: dict[str, Any] = field(default_factory=dict)


def _config_dependent_detail(**extra: Any) -> dict[str, Any]:
    return {"config_file": CODE_MAP_FILENAME, "verified": False, **extra}


def evaluate_tds(order_id: str, ledger_row: dict[str, Any]) -> TDSFinding | None:
    """Validate one ledger row's TDS fields. Returns None if TDS looks correct
    or the order carries no TDS at all."""
    tds_amount = ledger_row["tds_amount"]
    if tds_amount <= 0:
        return None

    legacy = ledger_row.get("tds_section_legacy") or None
    new_code = ledger_row.get("tds_code_new") or None
    gross = ledger_row["gross_amount"]
    posted_at = ledger_row["posted_at"]

    # Rule A: migration break.
    if posted_at >= TDS_CUTOVER and new_code is None and legacy is not None:
        suggested_code = None
        try:
            suggested_code = lookup_new_code(legacy).new_code
        except UnknownTDSCodeError:
            pass
        return TDSFinding(
            rule_id="TDS_RULE_A_MIGRATION_BREAK",
            taxonomy_code="TDS_CODE_MIGRATION_BREAK",
            amount_impact=tds_amount,
            confidence="config_dependent",
            detail=_config_dependent_detail(
                order_id=order_id, legacy_section=legacy, suggested_code=suggested_code
            ),
        )

    # Rule B: contradiction.
    mapped_entry = None
    if legacy is not None:
        try:
            mapped_entry = lookup_new_code(legacy)
        except UnknownTDSCodeError:
            mapped_entry = None
        if mapped_entry is not None and new_code is not None and mapped_entry.new_code != new_code:
            return TDSFinding(
                rule_id="TDS_RULE_B_CONTRADICTION",
                taxonomy_code="TDS_CODE_MIGRATION_BREAK",
                amount_impact=tds_amount,
                confidence="config_dependent",
                detail=_config_dependent_detail(
                    order_id=order_id,
                    legacy_section=legacy,
                    recorded_new_code=new_code,
                    expected_new_code=mapped_entry.new_code,
                ),
            )

    effective_code = new_code or (mapped_entry.new_code if mapped_entry else None)
    if effective_code is None:
        return None  # no resolvable code at all; not one of these 5 rules' territory

    # Rule E: code not in the rate schedule.
    has_pan = ledger_row.get("vendor_pan_masked") != "PANNOTAVAIL"
    try:
        rate_entry = lookup_rate(effective_code)
    except UnknownTDSCodeError:
        return TDSFinding(
            rule_id="TDS_RULE_E_UNKNOWN_CODE",
            taxonomy_code="TDS_RATE_MISMATCH",
            amount_impact=tds_amount,
            confidence="config_dependent",
            detail=_config_dependent_detail(order_id=order_id, unknown_code=effective_code),
        )

    scheduled_rate = rate_entry.rate_with_pan if has_pan else rate_entry.rate_without_pan

    # Rule D: absolute amount mismatch (checked before Rule C; see module docstring).
    expected_tds = _q(gross * scheduled_rate)
    amount_delta = abs(tds_amount - expected_tds)
    if amount_delta > AMOUNT_TOLERANCE:
        return TDSFinding(
            rule_id="TDS_RULE_D_AMOUNT_MISMATCH",
            taxonomy_code="TDS_AMOUNT_MISMATCH",
            amount_impact=amount_delta,
            confidence="high",
            detail={
                "order_id": order_id,
                "expected_tds": str(expected_tds),
                "actual_tds": str(tds_amount),
                "scheduled_rate": str(scheduled_rate),
            },
        )

    # Rule C: implied rate mismatch.
    implied_rate = (tds_amount / gross).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    if abs(implied_rate - scheduled_rate) > RATE_TOLERANCE:
        return TDSFinding(
            rule_id="TDS_RULE_C_RATE_MISMATCH",
            taxonomy_code="TDS_RATE_MISMATCH",
            amount_impact=amount_delta,
            confidence="high",
            detail={
                "order_id": order_id,
                "implied_rate": str(implied_rate),
                "scheduled_rate": str(scheduled_rate),
            },
        )

    return None
