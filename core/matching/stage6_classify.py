"""Stage 6: assign a taxonomy code to every remaining unmatched record.

Uses only attribution already recorded by earlier stages -- this module
does no new detection work of its own. Anything with no attribution
becomes UNEXPLAINED; that's a legitimate terminal state, never forced into
a guess.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from core.matching.stage2_bridge import BridgeResult
from core.matching.stage4_tds import TDSFinding
from core.models import Exception_
from core.taxonomy import TAXONOMY, ExceptionCode


def _make(
    code: ExceptionCode,
    row_ids: list[str],
    amount_impact,
    detail: dict[str, Any],
    id_hint: str | None = None,
) -> Exception_:
    # Derived from content, not a counter: two pipeline runs on the same
    # seed must produce byte-identical exception_ids, and a shared global
    # counter would drift across repeated in-process runs (e.g. successive
    # Streamlit clicks) even with identical input. id_hint keeps the id
    # compact for findings with many row_ids (e.g. a whole settlement batch).
    entry = TAXONOMY[code]
    key = id_hint if id_hint is not None else "_".join(str(r) for r in row_ids)
    exception_id = f"exc_{code.value.lower()}_{key}"
    return Exception_(
        exception_id=exception_id,
        taxonomy_code=code.value,
        severity=entry.severity.value,
        row_ids=row_ids,
        amount_impact=amount_impact,
        detail=detail,
    )


def classify_bank_only(residue_bank: list[dict[str, Any]]) -> list[Exception_]:
    return [
        _make(
            ExceptionCode.BANK_ONLY,
            row_ids=[str(row["row_id"])],
            amount_impact=row["credit"],
            detail={"bank_row_id": row["row_id"], "narration": row["narration"]},
        )
        for row in residue_bank
    ]


def classify_ledger_only(residue_ledger: list[dict[str, Any]]) -> list[Exception_]:
    return [
        _make(
            ExceptionCode.LEDGER_ONLY,
            row_ids=[row["order_id"]],
            amount_impact=row["gross_amount"],
            detail={"order_id": row["order_id"]},
        )
        for row in residue_ledger
    ]


def classify_settlement_only(residue_settlement: list[dict[str, Any]]) -> list[Exception_]:
    return [
        _make(
            ExceptionCode.SETTLEMENT_ONLY,
            row_ids=[row["settlement_id"]],
            amount_impact=row["amount"],
            detail={"settlement_id": row["settlement_id"], "order_id": row.get("order_id")},
        )
        for row in residue_settlement
    ]


def classify_ambiguous(ambiguous: list[dict[str, Any]]) -> list[Exception_]:
    return [
        _make(
            ExceptionCode.AMBIGUOUS_MATCH,
            row_ids=[str(a.get("bank_row_id", ""))],
            amount_impact=Decimal("0"),
            detail=a,
        )
        for a in ambiguous
    ]


def _bridge_row_ids(bridge: BridgeResult) -> list[str]:
    seen: dict[str, None] = {}
    for step in bridge.steps:
        for row_id in step.constituent_row_ids:
            if row_id:
                seen[row_id] = None
    return list(seen) or [bridge.settlement_utr]


def classify_bridge_result(bridge: BridgeResult) -> Exception_ | None:
    """Return an exception for a bridge's finding, or None if it's fully clean.

    A batch can be both closed AND carry a rate_variance (money reconciles,
    but the recorded rate doesn't match contract) -- rate_variance is
    checked first since it's the more specific finding.
    """
    row_ids = _bridge_row_ids(bridge)
    if bridge.rate_variance is not None:
        code = ExceptionCode(bridge.rate_variance.rule)
        return _make(
            code,
            row_ids=row_ids,
            amount_impact=abs(bridge.residual),
            detail={"settlement_utr": bridge.settlement_utr, **bridge.rate_variance.detail},
            id_hint=bridge.settlement_utr,
        )
    if bridge.attribution is not None:
        rule = bridge.attribution.rule
        code = ExceptionCode.UNEXPLAINED if rule == "UNATTRIBUTED" else ExceptionCode(rule)
        return _make(
            code,
            row_ids=row_ids,
            amount_impact=abs(bridge.residual),
            detail={"settlement_utr": bridge.settlement_utr, **bridge.attribution.detail},
            id_hint=bridge.settlement_utr,
        )
    return None


def classify_tds_finding(order_id: str, finding: TDSFinding) -> Exception_:
    code = ExceptionCode(finding.taxonomy_code)
    return _make(
        code,
        row_ids=[order_id],
        amount_impact=finding.amount_impact,
        detail={"rule_id": finding.rule_id, "confidence": finding.confidence, **finding.detail},
    )


def classify_unexplained(row_ids: list[str], amount_impact, detail: dict[str, Any]) -> Exception_:
    return _make(
        ExceptionCode.UNEXPLAINED, row_ids=row_ids, amount_impact=amount_impact, detail=detail
    )
