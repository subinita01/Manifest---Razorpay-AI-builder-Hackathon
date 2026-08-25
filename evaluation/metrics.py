"""Score a pipeline RunResult against ground_truth.json.

Nothing here is rounded until display -- evaluation/report.py (or the UI)
owns presentation; this module returns exact figures.

Ground-truth label semantics, since they don't map onto the taxonomy 1:1:

  - "True match" set for matcher precision/recall = expected_matches PLUS
    any planted_exceptions entry that carries a bank_row_id/settlement_utr
    pairing (FEE_VARIANCE, GST_ON_MDR_VARIANCE, ROUNDING, TIMING_T_PLUS_N,
    UNEXPLAINED). All of these represent a real bank<->settlement
    correspondence the generator knows to be true, even though some of
    them are *also* flagged with an exception -- a batch can be correctly
    matched AND carry a rate-compliance finding at the same time; that's
    the whole point of Stage 2's audit running on top of Stage 1/5.

  - unresolvable_by_design's "detection rate" is scored as "did the system
    avoid a false confident match" (landed as AMBIGUOUS_MATCH or
    UNEXPLAINED), not literally "labelled UNEXPLAINED" -- this taxonomy
    splits the build plan's generic UNEXPLAINED into a more specific
    AMBIGUOUS_MATCH where the cause is known (two tied candidates), which
    is strictly more informative, not a different outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from core.pipeline import RunResult
from core.taxonomy import ExceptionCode

PUNT_LABELS = {"AMBIGUOUS_MATCH", "UNEXPLAINED"}


@dataclass
class PerClassMetric:
    precision: float
    recall: float
    f1: float
    support: int


@dataclass
class MetricsReport:
    auto_match_rate: float
    matcher_precision: float
    matcher_recall: float
    exception_macro_f1: float
    exception_per_class: dict[str, PerClassMetric] = field(default_factory=dict)
    false_positive_cost_inr: Decimal = Decimal("0")
    unexplained_rate: float = 0.0
    unresolvable_by_design_detection_rate: float = 0.0
    wall_clock_ms: float = 0.0


FLAGGED_BUT_TRUE_MATCH_LABELS = (
    "FEE_VARIANCE",
    "GST_ON_MDR_VARIANCE",
    "ROUNDING",
    "TIMING_T_PLUS_N",
    "UNEXPLAINED",
)


def _true_pairings(
    ground_truth: dict[str, Any], settlement_utr_by_id: dict[str, str]
) -> dict[int, str]:
    """bank_row_id -> settlement_utr for every real bank<->settlement pairing.

    Only expected_matches carries settlement_utr directly; the flagged
    categories (FEE_VARIANCE etc.) only record settlement_ids, so their
    UTR is resolved via settlement_utr_by_id (built from the actual
    settlement rows, not re-derived from the id string).
    """
    pairings: dict[int, str] = {}
    for m in ground_truth["expected_matches"]:
        pairings[m["bank_row_id"]] = m["settlement_utr"]
    for e in ground_truth["planted_exceptions"]:
        if e["true_label"] in FLAGGED_BUT_TRUE_MATCH_LABELS:
            bank_row_id = e.get("bank_row_id")
            settlement_ids = e.get("settlement_ids") or []
            if bank_row_id is None or not settlement_ids:
                continue
            utr = settlement_utr_by_id.get(settlement_ids[0])
            if utr is not None:
                pairings[bank_row_id] = utr
    return pairings


def _bank_row_true_labels(ground_truth: dict[str, Any]) -> dict[int, str]:
    labels: dict[int, str] = {}
    for m in ground_truth["expected_matches"]:
        labels[m["bank_row_id"]] = "CLEAN"
    for e in ground_truth["planted_exceptions"]:
        if "bank_row_id" in e:
            labels[e["bank_row_id"]] = e["true_label"]
    for u in ground_truth["unresolvable_by_design"]:
        labels[u["bank_row_id"]] = "UNRESOLVABLE_BY_DESIGN"
    return labels


def _order_true_labels(ground_truth: dict[str, Any]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for m in ground_truth["expected_matches"]:
        for order_id in m["order_ids"]:
            labels[order_id] = "CLEAN"
    for e in ground_truth["planted_exceptions"]:
        if e["true_label"] in ("TDS_CODE_MIGRATION_BREAK", "TDS_AMOUNT_MISMATCH", "LEDGER_ONLY"):
            for order_id in e.get("order_ids", []):
                labels[order_id] = e["true_label"]
    return labels


def _predicted_bank_row_labels(result: RunResult, n_bank_rows: int) -> dict[int, str]:
    labels: dict[int, str] = {i: "CLEAN" for i in range(n_bank_rows)}

    bank_row_to_utr: dict[int, str] = {}
    for m in list(result.matched) + list(result.needs_review):
        if m.bank_row_id is not None and m.settlement_row_id:
            bank_row_to_utr[int(m.bank_row_id)] = m.settlement_row_id

    utr_to_exception_code: dict[str, str] = {}
    for e in result.exceptions:
        utr = e.detail.get("settlement_utr")
        if utr:
            utr_to_exception_code[utr] = e.taxonomy_code

    for m in result.needs_review:
        if m.bank_row_id is not None:
            labels[int(m.bank_row_id)] = "NEEDS_REVIEW"

    for m in result.matched:
        if m.bank_row_id is None:
            continue
        bank_row_id = int(m.bank_row_id)
        utr = bank_row_to_utr.get(bank_row_id)
        labels[bank_row_id] = utr_to_exception_code.get(utr, "CLEAN") if utr else "CLEAN"

    for e in result.exceptions:
        bank_row_id = e.detail.get("bank_row_id")
        if bank_row_id is not None:
            labels[int(bank_row_id)] = e.taxonomy_code

    return labels


def _predicted_order_labels(result: RunResult) -> dict[str, str]:
    labels: dict[str, str] = {}
    for e in result.exceptions:
        if e.taxonomy_code in (
            "TDS_CODE_MIGRATION_BREAK",
            "TDS_RATE_MISMATCH",
            "TDS_AMOUNT_MISMATCH",
        ):
            order_id = e.detail.get("order_id")
            if order_id:
                labels[order_id] = e.taxonomy_code
        elif e.taxonomy_code == "LEDGER_ONLY":
            for order_id in e.row_ids:
                labels[order_id] = "LEDGER_ONLY"
    return labels


def _precision_recall_f1(
    tp: int, predicted_positive: int, actual_positive: int
) -> tuple[float, float, float]:
    precision = tp / predicted_positive if predicted_positive else 0.0
    recall = tp / actual_positive if actual_positive else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


def _macro_f1(
    true_labels: list[str], predicted_labels: list[str], class_universe: set[str] | None = None
) -> tuple[float, dict[str, PerClassMetric]]:
    """class_universe restricts which classes are averaged over. Without it,
    any label that only ever appears as a *prediction* (e.g. NEEDS_REVIEW,
    a pipeline disposition, not a taxonomy classification) becomes its own
    phantom zero-support class and drags the average down for existing
    purely as noise -- the underlying miss is already reflected in the
    true class's own recall.
    """
    classes = (
        sorted((set(true_labels) | set(predicted_labels)) & class_universe)
        if class_universe
        else sorted(set(true_labels) | set(predicted_labels))
    )
    per_class: dict[str, PerClassMetric] = {}
    for cls in classes:
        tp = sum(1 for t, p in zip(true_labels, predicted_labels) if t == cls and p == cls)
        predicted_positive = sum(1 for p in predicted_labels if p == cls)
        actual_positive = sum(1 for t in true_labels if t == cls)
        precision, recall, f1 = _precision_recall_f1(tp, predicted_positive, actual_positive)
        per_class[cls] = PerClassMetric(precision, recall, f1, support=actual_positive)
    macro_f1 = sum(m.f1 for m in per_class.values()) / len(per_class) if per_class else 0.0
    return macro_f1, per_class


def evaluate_run(
    result: RunResult,
    ground_truth: dict[str, Any],
    n_bank_rows: int,
    bank_credit_by_row: dict[int, Decimal],
    settlement_utr_by_id: dict[str, str],
    wall_clock_ms: float = 0.0,
) -> MetricsReport:
    # --- matcher precision/recall ---
    true_utr_by_bank_row = _true_pairings(ground_truth, settlement_utr_by_id)

    predicted_pairs = {
        int(m.bank_row_id): m.settlement_row_id for m in result.matched if m.bank_row_id is not None
    }

    correct = 0
    false_positive_cost = Decimal("0")
    for bank_row_id, predicted_utr in predicted_pairs.items():
        expected_utr = true_utr_by_bank_row.get(bank_row_id)
        if expected_utr is not None and expected_utr == predicted_utr:
            correct += 1
        else:
            # Either no ground-truth pairing exists for this bank row at
            # all (e.g. it should have been BANK_ONLY), or the matcher
            # picked the wrong settlement -- both misallocate the credit.
            false_positive_cost += abs(bank_credit_by_row.get(bank_row_id, Decimal("0")))

    matcher_precision, matcher_recall, _ = _precision_recall_f1(
        correct, len(predicted_pairs), len(true_utr_by_bank_row)
    )

    auto_match_rate = len(result.matched) / n_bank_rows if n_bank_rows else 0.0

    # --- exception classification macro-F1 (bank-row level + order level) ---
    # unresolvable_by_design rows are excluded here: by construction they
    # have no single correct taxonomy code, so scoring them against one
    # would double-penalize what unresolvable_by_design_detection_rate
    # already measures fairly (did the system avoid a false confident
    # match), inventing two phantom zero-score classes in the process.
    bank_true = _bank_row_true_labels(ground_truth)
    bank_predicted = _predicted_bank_row_labels(result, n_bank_rows)
    order_true = _order_true_labels(ground_truth)
    order_predicted = _predicted_order_labels(result)

    unresolvable_bank_row_ids = {u["bank_row_id"] for u in ground_truth["unresolvable_by_design"]}
    scoreable_bank_rows = [i for i in range(n_bank_rows) if i not in unresolvable_bank_row_ids]

    true_labels = [bank_true.get(i, "CLEAN") for i in scoreable_bank_rows]
    predicted_labels = [bank_predicted.get(i, "CLEAN") for i in scoreable_bank_rows]

    order_ids = sorted(set(order_true) | set(order_predicted))
    true_labels += [order_true.get(oid, "CLEAN") for oid in order_ids]
    predicted_labels += [order_predicted.get(oid, "CLEAN") for oid in order_ids]

    # Every taxonomy code (whether or not it happens to appear in this run)
    # plus every real ground-truth category, even ones the cascade has no
    # detector for at all (e.g. TIMING_T_PLUS_N) -- that's a genuine
    # recall=0 finding worth surfacing, not noise to filter out. Only pure
    # prediction-only labels (pipeline dispositions like NEEDS_REVIEW that
    # were never a true category) get excluded.
    class_universe = {code.value for code in ExceptionCode} | {"CLEAN"} | set(true_labels)
    macro_f1, per_class = _macro_f1(true_labels, predicted_labels, class_universe)

    # --- unresolvable_by_design detection rate ---
    unresolvable = ground_truth["unresolvable_by_design"]
    punted = sum(1 for u in unresolvable if bank_predicted.get(u["bank_row_id"]) in PUNT_LABELS)
    unresolvable_rate = punted / len(unresolvable) if unresolvable else 0.0

    bank_predicted_labels = list(bank_predicted.values())
    unexplained_rate = sum(1 for lbl in bank_predicted_labels if lbl == "UNEXPLAINED") / len(
        bank_predicted_labels
    )

    return MetricsReport(
        auto_match_rate=auto_match_rate,
        matcher_precision=matcher_precision,
        matcher_recall=matcher_recall,
        exception_macro_f1=macro_f1,
        exception_per_class=per_class,
        false_positive_cost_inr=false_positive_cost,
        unexplained_rate=unexplained_rate,
        unresolvable_by_design_detection_rate=unresolvable_rate,
        wall_clock_ms=wall_clock_ms,
    )
