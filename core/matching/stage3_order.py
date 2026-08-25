"""Stage 3: match settlement payment rows to ledger rows on order_id.

core.models.LedgerRow has no payment_id field -- the ledger is an
accounting-side record keyed by order_id/invoice_no, not a gateway-side
record -- so there is no payment_id to fall back to as the build plan
describes. Every settlement row in this data model always carries an
order_id, so that fallback path is unreachable here and isn't implemented.

Unmatched settlement rows (SETTLEMENT_ONLY) and unmatched ledger rows
(LEDGER_ONLY) are left in residue for Stage 6 to classify.
"""

from __future__ import annotations

import time
from typing import Any

from core.matching.stage_result import StageResult
from core.models import TOLERANCE, MatchResult


def match_order(
    settlement_rows: list[dict[str, Any]], ledger_rows: list[dict[str, Any]]
) -> StageResult:
    start = time.perf_counter()
    result = StageResult(stage_name="stage3_order")

    ledger_by_order = {row["order_id"]: row for row in ledger_rows}
    payment_rows = [r for r in settlement_rows if r["type"] == "payment"]

    matched_settlement_ids: set[str] = set()
    matched_order_ids: set[str] = set()

    for row in payment_rows:
        order_id = row.get("order_id")
        ledger_row = ledger_by_order.get(order_id) if order_id else None
        if ledger_row is None:
            continue
        if abs(row["amount"] - ledger_row["gross_amount"]) > TOLERANCE:
            continue

        result.matched.append(
            MatchResult(
                match_id=f"stage3_{row['settlement_id']}_{order_id}",
                stage_name="stage3_order",
                settlement_row_id=row["settlement_id"],
                ledger_row_id=order_id,
                confidence=1.0,
                detail={"order_id": order_id},
            )
        )
        matched_settlement_ids.add(row["settlement_id"])
        matched_order_ids.add(order_id)

    result.residue_settlement = [
        r for r in payment_rows if r["settlement_id"] not in matched_settlement_ids
    ]
    result.residue_ledger = [r for r in ledger_rows if r["order_id"] not in matched_order_ids]
    result.elapsed_ms = (time.perf_counter() - start) * 1000
    return result
