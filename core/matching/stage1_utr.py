"""Stage 1: exact UTR matching between bank credits and settlement batches.

A match requires ALL of:
  - extracted UTR equals settlement_utr (exact, case-insensitive)
  - |bank.credit - sum(settlement net for that UTR)| <= TOLERANCE
  - |bank.txn_date - settlement.settled_at.date()| <= 2 days

If a UTR is claimed by more than one bank row, none of them are matched:
an AMBIGUOUS_MATCH candidate is emitted instead. Never pick arbitrarily.
"""

from __future__ import annotations

import time
from collections import defaultdict
from decimal import Decimal
from typing import Any

from core.matching.stage_result import StageResult
from core.models import TOLERANCE, MatchResult
from core.normalize import extract_utr

DATE_TOLERANCE_DAYS = 2


def _settlement_net(rows: list[dict[str, Any]]) -> Decimal:
    net = Decimal("0")
    for row in rows:
        if row["type"] == "payment" and not row["on_hold"]:
            net += row["amount"] - row["fee"] - row["tax"]
        elif row["type"] in ("refund", "adjustment"):
            net += row["amount"]
    return net


def _group_by_utr(settlement_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in settlement_rows:
        groups[row["settlement_utr"].upper()].append(row)
    return groups


def match_utr(
    bank_rows: list[dict[str, Any]], settlement_rows: list[dict[str, Any]]
) -> StageResult:
    start = time.perf_counter()
    settlement_groups = _group_by_utr(settlement_rows)

    extracted: dict[int, str] = {}
    for bank_row in bank_rows:
        utr = extract_utr(bank_row["narration"])
        if utr is not None:
            extracted[bank_row["row_id"]] = utr.upper()

    claims: dict[str, list[int]] = defaultdict(list)
    for row_id, utr in extracted.items():
        claims[utr].append(row_id)

    bank_by_id = {row["row_id"]: row for row in bank_rows}
    matched_bank_ids: set[int] = set()
    ambiguous_bank_ids: set[int] = set()
    matched_settlement_utrs: set[str] = set()
    result = StageResult(stage_name="stage1_utr")

    for utr, row_ids in claims.items():
        group = settlement_groups.get(utr)
        if group is None:
            continue

        if len(row_ids) > 1:
            for row_id in row_ids:
                ambiguous_bank_ids.add(row_id)
                result.ambiguous.append(
                    {
                        "reason": "utr_claimed_by_multiple_bank_rows",
                        "bank_row_id": row_id,
                        "settlement_utr": utr,
                        "candidate_bank_row_ids": row_ids,
                    }
                )
            continue

        bank_row = bank_by_id[row_ids[0]]
        expected_net = _settlement_net(group)
        settled_dates = {row["settled_at"].date() for row in group}
        if len(settled_dates) != 1:
            continue
        settled_date = next(iter(settled_dates))

        amount_ok = abs(bank_row["credit"] - expected_net) <= TOLERANCE
        date_ok = abs((bank_row["txn_date"] - settled_date).days) <= DATE_TOLERANCE_DAYS

        if amount_ok and date_ok:
            result.matched.append(
                MatchResult(
                    match_id=f"stage1_{bank_row['row_id']}_{utr}",
                    stage_name="stage1_utr",
                    bank_row_id=str(bank_row["row_id"]),
                    settlement_row_id=utr,
                    confidence=1.0,
                    detail={
                        "settlement_ids": [row["settlement_id"] for row in group],
                        "order_ids": [row["order_id"] for row in group if row["order_id"]],
                        "expected_net": str(expected_net),
                    },
                )
            )
            matched_bank_ids.add(bank_row["row_id"])
            matched_settlement_utrs.add(utr)

    excluded_bank_ids = matched_bank_ids | ambiguous_bank_ids
    result.residue_bank = [row for row in bank_rows if row["row_id"] not in excluded_bank_ids]
    result.residue_settlement = [
        row
        for row in settlement_rows
        if row["settlement_utr"].upper() not in matched_settlement_utrs
    ]
    result.elapsed_ms = (time.perf_counter() - start) * 1000
    return result
