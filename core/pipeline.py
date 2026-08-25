"""Pipeline orchestrator: runs Stages 1-6 in order and enforces the core
invariant -- matched + needs_review + exceptions == total_input_rows.

Raises InvariantViolation loudly on failure rather than logging and
continuing: a silently dropped row is exactly the failure mode this product
exists to prevent.

Accounting note: total_input_rows counts every bank, settlement, and ledger
row exactly once. A settlement row can be touched by two independent match
relationships at once -- the bank-matching path (Stage 1/5, keyed by UTR)
and the ledger-matching path (Stage 3, keyed by order_id) -- so its final
disposition is a union of both: EXCEPTION if either side flagged a problem
(including an annotation-style finding like FEE_VARIANCE or a TDS finding
on an otherwise-successful match -- a flagged transaction is still an open
issue, not a clean match, per the "100% match with zero exceptions is a
failure state" rule), else NEEDS_REVIEW if either side proposed one, else
MATCHED. Exception status always takes priority over matched/needs_review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.matching.stage1_utr import match_utr
from core.matching.stage2_bridge import build_bridge
from core.matching.stage3_order import match_order
from core.matching.stage4_tds import evaluate_tds
from core.matching.stage5_fuzzy import match_fuzzy
from core.matching.stage6_classify import (
    classify_ambiguous,
    classify_bank_only,
    classify_bridge_result,
    classify_ledger_only,
    classify_settlement_only,
    classify_tds_finding,
)
from core.matching.stage_result import StageResult
from core.models import Exception_, MatchResult


class InvariantViolation(RuntimeError):
    """Raised when matched + needs_review + exceptions != total_input_rows."""


@dataclass
class RunResult:
    matched: list[MatchResult] = field(default_factory=list)
    needs_review: list[MatchResult] = field(default_factory=list)
    exceptions: list[Exception_] = field(default_factory=list)
    stage_results: dict[str, StageResult] = field(default_factory=dict)
    total_input_rows: int = 0
    matched_row_count: int = 0
    needs_review_row_count: int = 0
    exception_row_count: int = 0


def run_pipeline(
    bank_rows: list[dict[str, Any]],
    settlement_rows: list[dict[str, Any]],
    ledger_rows: list[dict[str, Any]],
) -> RunResult:
    total_input_rows = len(bank_rows) + len(settlement_rows) + len(ledger_rows)

    stage1 = match_utr(bank_rows, settlement_rows)
    stage5 = match_fuzzy(stage1.residue_bank, stage1.residue_settlement)
    stage3 = match_order(settlement_rows, ledger_rows)

    matched: list[MatchResult] = list(stage1.matched) + list(stage5.matched)
    needs_review: list[MatchResult] = list(stage5.needs_review)
    exceptions: list[Exception_] = []

    # --- Stage 2: bridge audit for every settlement UTR-group Stage 1/5 matched.
    settlement_by_utr: dict[str, list[dict[str, Any]]] = {}
    for row in settlement_rows:
        settlement_by_utr.setdefault(row["settlement_utr"], []).append(row)
    bank_by_id = {row["row_id"]: row for row in bank_rows}

    flagged_settlement_ids: set[str] = set()
    flagged_bank_ids: set[Any] = set()
    for match in list(stage1.matched) + list(stage5.matched):
        utr = match.settlement_row_id
        rows = settlement_by_utr.get(utr, [])
        bank_row = bank_by_id.get(int(match.bank_row_id)) if match.bank_row_id is not None else None
        if not rows or bank_row is None:
            continue
        bridge = build_bridge(utr, rows, bank_row["credit"])
        exc = classify_bridge_result(bridge)
        if exc is not None:
            exceptions.append(exc)
            flagged_settlement_ids.update(row["settlement_id"] for row in rows)
            flagged_bank_ids.add(bank_row["row_id"])

    # --- Stage 4: TDS validation for every order Stage 3 matched.
    ledger_by_order = {row["order_id"]: row for row in ledger_rows}
    flagged_order_ids: set[str] = set()
    for match in stage3.matched:
        order_id = match.ledger_row_id
        ledger_row = ledger_by_order.get(order_id)
        if ledger_row is None:
            continue
        finding = evaluate_tds(order_id, ledger_row)
        if finding is not None:
            exceptions.append(classify_tds_finding(order_id, finding))
            flagged_order_ids.add(order_id)

    # --- Stage 6: structural exceptions for whatever never matched at all.
    # SETTLEMENT_ONLY is specifically "no ledger row for this settlement"
    # (Stage 3's residue) -- a settlement row that failed bank-side matching
    # but does have a ledger row (e.g. a TIMING_T_PLUS_N case, where the
    # bank credit landed outside date tolerance) is still "explained" via
    # its order; the corresponding bank row is what surfaces as unexplained.
    exceptions.extend(classify_ambiguous(stage1.ambiguous))
    exceptions.extend(classify_ambiguous(stage5.ambiguous))
    exceptions.extend(classify_bank_only(stage5.residue_bank))
    exceptions.extend(classify_ledger_only(stage3.residue_ledger))
    exceptions.extend(classify_settlement_only(stage3.residue_settlement))

    # --- Row-level disposition accounting for the invariant.
    ambiguous_bank_ids = {a["bank_row_id"] for a in stage1.ambiguous} | {
        a["bank_row_id"] for a in stage5.ambiguous
    }
    matched_bank_ids = {int(m.bank_row_id) for m in matched if m.bank_row_id is not None}
    review_bank_ids = {int(m.bank_row_id) for m in needs_review if m.bank_row_id is not None}
    bank_only_ids = {row["row_id"] for row in stage5.residue_bank}

    bank_exception = ambiguous_bank_ids | bank_only_ids | flagged_bank_ids
    bank_matched = matched_bank_ids - bank_exception
    bank_review = review_bank_ids - bank_exception - bank_matched

    all_settlement_ids = {row["settlement_id"] for row in settlement_rows}
    settlement_only_ids = {row["settlement_id"] for row in stage3.residue_settlement}
    settlement_exception = flagged_settlement_ids | settlement_only_ids
    settlement_matched = all_settlement_ids - settlement_exception

    matched_ledger_ids = {m.ledger_row_id for m in stage3.matched}
    ledger_only_ids = {row["order_id"] for row in stage3.residue_ledger}
    ledger_exception = flagged_order_ids | ledger_only_ids
    ledger_matched = matched_ledger_ids - ledger_exception

    matched_row_count = len(bank_matched) + len(settlement_matched) + len(ledger_matched)
    needs_review_row_count = len(bank_review)
    exception_row_count = len(bank_exception) + len(settlement_exception) + len(ledger_exception)

    accounted = matched_row_count + needs_review_row_count + exception_row_count
    if accounted != total_input_rows:
        raise InvariantViolation(
            f"matched({matched_row_count}) + needs_review({needs_review_row_count}) + "
            f"exceptions({exception_row_count}) = {accounted}, expected "
            f"total_input_rows={total_input_rows}"
        )

    return RunResult(
        matched=matched,
        needs_review=needs_review,
        exceptions=exceptions,
        stage_results={
            "stage1_utr": stage1,
            "stage3_order": stage3,
            "stage5_fuzzy": stage5,
        },
        total_input_rows=total_input_rows,
        matched_row_count=matched_row_count,
        needs_review_row_count=needs_review_row_count,
        exception_row_count=exception_row_count,
    )
