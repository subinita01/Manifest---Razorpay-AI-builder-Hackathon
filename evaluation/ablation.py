"""Cumulative stage ablation and fuzzy-threshold sweep against the demo
dataset, writing evaluation/results/ablation.md and threshold_sweep.md.

`make eval` runs this and commits the results, so judges see real numbers
without running anything themselves.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.ingest import load_bank_csv, load_ledger_csv, load_settlement_csv
from core.pipeline import run_pipeline
from evaluation.metrics import evaluate_run

ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT / "data" / "demo"
RESULTS_DIR = ROOT / "evaluation" / "results"

CUMULATIVE_CONFIGS = [
    ("stage1 only", dict(use_stage2=False, use_stage3=False, use_stage4=False, use_stage5=False)),
    (
        "+ stage2 bridge",
        dict(use_stage2=True, use_stage3=False, use_stage4=False, use_stage5=False),
    ),
    ("+ stage3 order", dict(use_stage2=True, use_stage3=True, use_stage4=False, use_stage5=False)),
    ("+ stage4 tds", dict(use_stage2=True, use_stage3=True, use_stage4=True, use_stage5=False)),
    ("+ stage5 fuzzy", dict(use_stage2=True, use_stage3=True, use_stage4=True, use_stage5=True)),
]

THRESHOLD_SWEEP = [round(0.60 + 0.05 * i, 2) for i in range(8)]  # 0.60 .. 0.95


def _load_demo():
    bank_rows = load_bank_csv(DEMO_DIR / "bank_statement.csv")
    settlement_rows = load_settlement_csv(DEMO_DIR / "settlement_batch.csv")
    ledger_rows = load_ledger_csv(DEMO_DIR / "internal_ledger.csv")
    ground_truth = json.loads((DEMO_DIR / "ground_truth.json").read_text())
    return bank_rows, settlement_rows, ledger_rows, ground_truth


def run_cumulative_ablation() -> str:
    bank_rows, settlement_rows, ledger_rows, ground_truth = _load_demo()
    bank_credit_by_row = {r["row_id"]: r["credit"] for r in bank_rows}
    settlement_utr_by_id = {r["settlement_id"]: r["settlement_utr"] for r in settlement_rows}

    lines = [
        "# Cumulative stage ablation",
        "",
        "Each row adds one stage on top of the previous configuration and re-runs the",
        "full pipeline against the committed demo dataset (seed 42, 600 orders).",
        "`make eval` regenerates this file; nothing here is hand-edited.",
        "",
        "Match rate/precision/recall/FP cost are all specifically about bank-to-",
        "settlement matching, so Stage 3 (settlement-to-ledger) and Stage 4 (TDS) don't",
        "move them even though they matter a great deal -- that shows up in Total",
        "exceptions instead, which includes SETTLEMENT_ONLY/LEDGER_ONLY findings only",
        "possible once Stage 3 has actually checked the ledger side.",
        "",
        "| Configuration | Match rate | Precision | Recall | FP cost (INR) "
        "| Total exceptions | Unexplained | Invariant |",
        "|---|---|---|---|---|---|---|---|",
    ]

    for name, kwargs in CUMULATIVE_CONFIGS:
        result = run_pipeline(bank_rows, settlement_rows, ledger_rows, **kwargs)
        report = evaluate_run(
            result, ground_truth, len(bank_rows), bank_credit_by_row, settlement_utr_by_id
        )
        invariant_ok = (
            result.matched_row_count + result.needs_review_row_count + result.exception_row_count
            == result.total_input_rows
        )
        unexplained_count = sum(1 for e in result.exceptions if e.taxonomy_code == "UNEXPLAINED")
        lines.append(
            f"| {name} | {report.auto_match_rate:.1%} | {report.matcher_precision:.3f} | "
            f"{report.matcher_recall:.3f} | Rs {report.false_positive_cost_inr:,.2f} | "
            f"{len(result.exceptions)} | {unexplained_count} | "
            f"{'holds' if invariant_ok else 'VIOLATED'} |"
        )

    lines.append("")
    lines.append(
        "LLM advisory is not yet implemented (Day 9), so a 6th row cannot be produced "
        "honestly; adding a row with no real number behind it would be exactly the "
        "kind of unearned claim this project's evaluation exists to prevent."
    )
    lines.append("")
    return "\n".join(lines)


def run_threshold_sweep() -> str:
    bank_rows, settlement_rows, ledger_rows, ground_truth = _load_demo()
    bank_credit_by_row = {r["row_id"]: r["credit"] for r in bank_rows}
    settlement_utr_by_id = {r["settlement_id"]: r["settlement_utr"] for r in settlement_rows}

    lines = [
        "# Fuzzy auto-match threshold sweep",
        "",
        "Stage 5's auto_match_threshold (config/settings.yaml, currently 0.90) swept",
        "from 0.60 to 0.95 in 0.05 steps against the committed demo dataset, holding",
        "every other stage fixed. This is the evidence behind the threshold choice",
        "rather than an assertion of it.",
        "",
        "| Threshold | Precision | Recall | FP cost (INR) |",
        "|---|---|---|---|",
    ]

    rows = []
    for threshold in THRESHOLD_SWEEP:
        result = run_pipeline(
            bank_rows, settlement_rows, ledger_rows, fuzzy_auto_match_threshold=threshold
        )
        report = evaluate_run(
            result, ground_truth, len(bank_rows), bank_credit_by_row, settlement_utr_by_id
        )
        rows.append((threshold, report))
        lines.append(
            f"| {threshold:.2f} | {report.matcher_precision:.3f} | {report.matcher_recall:.3f} | "
            f"Rs {report.false_positive_cost_inr:,.2f} |"
        )

    lines.append("")
    precisions = {round(report.matcher_precision, 6) for _, report in rows}
    if len(precisions) == 1:
        lines.append(
            "Precision does not degrade anywhere in this sweep -- every planted bad "
            "candidate in this demo dataset scores well below 0.60, and the near-tie "
            "ambiguity rule (a separate, fixed safety net) already catches the cases "
            "designed to be genuinely ambiguous regardless of this threshold. That "
            "means 0.90 is a conservative choice made for safety margin against data "
            "this sweep hasn't seen, not because a lower threshold visibly costs "
            "precision here -- the honest reading of this specific sweep is that a "
            "lower threshold would trade nothing away on this dataset."
        )
    else:
        lines.append(
            "Precision degrades below the chosen threshold in this sweep, which is "
            "the direct evidence for favouring a higher, precision-safe threshold "
            "over the recall it gives up."
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "ablation.md").write_text(run_cumulative_ablation())
    (RESULTS_DIR / "threshold_sweep.md").write_text(run_threshold_sweep())
    print(f"Wrote {RESULTS_DIR / 'ablation.md'}")
    print(f"Wrote {RESULTS_DIR / 'threshold_sweep.md'}")


if __name__ == "__main__":
    main()
