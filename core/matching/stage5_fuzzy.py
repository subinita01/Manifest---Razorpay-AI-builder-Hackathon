"""Stage 5: fuzzy matching over Stage 1's residue only.

score = 0.5 * amount_score + 0.2 * date_score + 0.3 * narration_score

  - amount_score: 1.0 at an exact amount match, decaying linearly to 0 at
    max(Rs 5, 0.5% of the candidate's net) -- a floor so small transactions
    aren't held to an unreasonably tight absolute tolerance.
  - date_score: 1.0 same day, decaying linearly to 0 at 3 days.
  - narration_score: rapidfuzz token_set_ratio(bank narration, settlement
    UTR) / 100 -- catches a truncated UTR that still shares digits with the
    true one.

Thresholds come from config/settings.yaml, never hardcoded:
  >= auto_match_threshold    -> auto-match
  needs_review_threshold..auto_match_threshold -> NEEDS_REVIEW (a proposal,
    never a match -- core/pipeline.py must never promote these on its own)
  < needs_review_threshold   -> left in residue

If the top two candidates for a bank row are within ambiguity_margin of
each other, the row is never matched or proposed -- it's emitted as
AMBIGUOUS_MATCH regardless of score, exactly like Stage 1's duplicate-UTR
rule. Never break a near-tie arbitrarily.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from rapidfuzz import fuzz

from core.config import load_settings
from core.matching.stage_result import StageResult
from core.models import MatchResult

MIN_AMOUNT_TOLERANCE = Decimal("5")
AMOUNT_TOLERANCE_RATE = Decimal("0.005")
DATE_TOLERANCE_DAYS = 3


@dataclass
class Candidate:
    settlement_utr: str
    net: Decimal
    settled_date: Any
    settlement_ids: list[str] = field(default_factory=list)
    order_ids: list[str] = field(default_factory=list)


def _fuzzy_settings() -> tuple[float, float, float]:
    settings = load_settings()["fuzzy_match"]
    return (
        float(settings["auto_match_threshold"]),
        float(settings["needs_review_threshold"]),
        float(settings["ambiguity_margin"]),
    )


def _amount_score(bank_credit: Decimal, net: Decimal) -> float:
    diff = abs(bank_credit - net)
    tolerance = max(MIN_AMOUNT_TOLERANCE, AMOUNT_TOLERANCE_RATE * abs(net))
    if tolerance == 0:
        return 1.0 if diff == 0 else 0.0
    return max(0.0, 1.0 - float(diff / tolerance))


def _date_score(bank_date, settled_date) -> float:
    delta_days = abs((bank_date - settled_date).days)
    return max(0.0, 1.0 - delta_days / DATE_TOLERANCE_DAYS)


def _narration_score(narration: str, settlement_utr: str) -> float:
    return fuzz.token_set_ratio(narration, settlement_utr) / 100.0


def _group_candidates(residue_settlement: list[dict[str, Any]]) -> list[Candidate]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in residue_settlement:
        groups[row["settlement_utr"]].append(row)

    candidates = []
    for utr, rows in groups.items():
        net = Decimal("0")
        for row in rows:
            if row["type"] == "payment" and not row["on_hold"]:
                net += row["amount"] - row["fee"] - row["tax"]
            elif row["type"] in ("refund", "adjustment"):
                net += row["amount"]
        settled_dates = {row["settled_at"].date() for row in rows}
        settled_date = next(iter(settled_dates)) if len(settled_dates) == 1 else None
        candidates.append(
            Candidate(
                settlement_utr=utr,
                net=net,
                settled_date=settled_date,
                settlement_ids=[r["settlement_id"] for r in rows],
                order_ids=[r["order_id"] for r in rows if r["order_id"]],
            )
        )
    return candidates


def match_fuzzy(
    residue_bank: list[dict[str, Any]],
    residue_settlement: list[dict[str, Any]],
    auto_match_threshold: float | None = None,
) -> StageResult:
    """auto_match_threshold overrides config/settings.yaml's value when set
    -- used by evaluation/ablation.py's threshold sweep so the sweep doesn't
    have to mutate the config file to explore other thresholds."""
    start = time.perf_counter()
    result = StageResult(stage_name="stage5_fuzzy")
    auto_threshold, review_threshold, ambiguity_margin = _fuzzy_settings()
    if auto_match_threshold is not None:
        auto_threshold = auto_match_threshold

    candidates = _group_candidates(residue_settlement)
    matched_utrs: set[str] = set()
    excluded_bank_ids: set[Any] = set()

    for bank_row in residue_bank:
        scored = []
        for candidate in candidates:
            if candidate.settled_date is None:
                continue
            amount_score = _amount_score(bank_row["credit"], candidate.net)
            date_score = _date_score(bank_row["txn_date"], candidate.settled_date)
            narration_score = _narration_score(bank_row["narration"], candidate.settlement_utr)
            score = 0.5 * amount_score + 0.2 * date_score + 0.3 * narration_score
            scored.append((score, candidate))

        if not scored:
            continue

        scored.sort(key=lambda pair: pair[0], reverse=True)
        top_score, top_candidate = scored[0]

        # A near-tie only matters when the top candidate would otherwise be
        # a real contender (>= review_threshold). Below that, every
        # candidate is a bad fit and will land in residue anyway -- treating
        # noise-level ties among uniformly poor scores as "ambiguous" would
        # mislabel e.g. a genuinely unmatched bank credit (BANK_ONLY) just
        # because two unrelated settlements happened to score similarly low.
        if (
            top_score >= review_threshold
            and len(scored) > 1
            and (top_score - scored[1][0]) <= ambiguity_margin
        ):
            result.ambiguous.append(
                {
                    "reason": "fuzzy_near_tie",
                    "bank_row_id": bank_row["row_id"],
                    "candidates": [
                        {"settlement_utr": c.settlement_utr, "score": round(s, 4)}
                        for s, c in scored[:3]
                    ],
                }
            )
            excluded_bank_ids.add(bank_row["row_id"])
            continue

        if top_score >= auto_threshold:
            result.matched.append(
                MatchResult(
                    match_id=f"stage5_{bank_row['row_id']}_{top_candidate.settlement_utr}",
                    stage_name="stage5_fuzzy",
                    bank_row_id=str(bank_row["row_id"]),
                    settlement_row_id=top_candidate.settlement_utr,
                    confidence=top_score,
                    detail={
                        "settlement_ids": top_candidate.settlement_ids,
                        "order_ids": top_candidate.order_ids,
                    },
                )
            )
            matched_utrs.add(top_candidate.settlement_utr)
            excluded_bank_ids.add(bank_row["row_id"])
        elif top_score >= review_threshold:
            result.needs_review.append(
                MatchResult(
                    match_id=f"stage5_review_{bank_row['row_id']}_{top_candidate.settlement_utr}",
                    stage_name="stage5_fuzzy",
                    bank_row_id=str(bank_row["row_id"]),
                    settlement_row_id=top_candidate.settlement_utr,
                    confidence=top_score,
                    detail={
                        "settlement_ids": top_candidate.settlement_ids,
                        "order_ids": top_candidate.order_ids,
                    },
                )
            )
            excluded_bank_ids.add(bank_row["row_id"])
        # else: below review_threshold, stays in residue untouched.

    result.residue_bank = [r for r in residue_bank if r["row_id"] not in excluded_bank_ids]
    result.residue_settlement = [
        r for r in residue_settlement if r["settlement_utr"] not in matched_utrs
    ]
    result.elapsed_ms = (time.perf_counter() - start) * 1000
    return result
