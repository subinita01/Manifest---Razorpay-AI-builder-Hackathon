"""CLI smoke test: load data/demo/, run Stage 1 + Stage 2, print sample waterfalls."""

from __future__ import annotations

import csv
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.matching.stage1_utr import match_utr  # noqa: E402
from core.matching.stage2_bridge import BridgeResult, build_bridge  # noqa: E402
from core.normalize import parse_date, parse_money  # noqa: E402


def load_bank(path: Path) -> list[dict]:
    rows = []
    with path.open() as f:
        for i, r in enumerate(csv.DictReader(f)):
            rows.append(
                {
                    "row_id": i,
                    "narration": r["narration"],
                    "credit": parse_money(r["credit"]),
                    "txn_date": parse_date(r["txn_date"]),
                }
            )
    return rows


def load_settlement(path: Path) -> list[dict]:
    rows = []
    with path.open() as f:
        for r in csv.DictReader(f):
            rows.append(
                {
                    "settlement_id": r["settlement_id"],
                    "settlement_utr": r["settlement_utr"],
                    "amount": Decimal(r["amount"]),
                    "fee": Decimal(r["fee"]),
                    "tax": Decimal(r["tax"]),
                    "on_hold": r["on_hold"] == "True",
                    "type": r["type"],
                    "settled_at": datetime.fromisoformat(r["settled_at"]),
                    "order_id": r["order_id"],
                    "dispute_id": r["dispute_id"] or None,
                }
            )
    return rows


def format_amount(value: Decimal) -> str:
    sign = "+" if value >= 0 else "-"
    return f"{sign}{abs(value):,.2f}"


def print_waterfall(result: BridgeResult) -> None:
    print(f"Settlement UTR {result.settlement_utr}")
    for step in result.steps:
        print(f"  {step.label:<28}{format_amount(step.amount):>15}{step.running_total:>18,.2f}")
    status = "CLOSED" if result.closed else "OPEN"
    print(f"  {'Bank credit':<28}{'':>15}{result.bank_credit:>18,.2f}")
    print(f"  {'Residual':<28}{'':>15}{result.residual:>18,.2f}  {status}")
    if result.attribution:
        print(f"  attribution:   {result.attribution.rule} {result.attribution.detail}")
    if result.rate_variance:
        print(f"  rate_variance: {result.rate_variance.rule} {result.rate_variance.detail}")
    print()


def main() -> None:
    demo_dir = ROOT / "data" / "demo"
    bank_rows = load_bank(demo_dir / "bank_statement.csv")
    settlement_rows = load_settlement(demo_dir / "settlement_batch.csv")

    stage1 = match_utr(bank_rows, settlement_rows)
    print(f"Stage 1: matched={len(stage1.matched)} residue_bank={len(stage1.residue_bank)}\n")

    bank_by_id = {row["row_id"]: row for row in bank_rows}
    settlement_by_utr: dict[str, list[dict]] = {}
    for row in settlement_rows:
        settlement_by_utr.setdefault(row["settlement_utr"], []).append(row)

    results = []
    for match in stage1.matched:
        utr = match.settlement_row_id
        bank_row = bank_by_id[int(match.bank_row_id)]
        rows = settlement_by_utr[utr]
        results.append(build_bridge(utr, rows, bank_row["credit"]))

    closed = [r for r in results if r.closed]
    variances = [r for r in results if r.rate_variance]
    print(
        f"Stage 2: {len(results)} bridges built, "
        f"{len(closed)} closed exactly, {len(variances)} rate variances\n"
    )

    clean = next((r for r in results if r.closed and not r.rate_variance), None)
    if clean:
        print("--- Example: a clean, closed bridge ---")
        print_waterfall(clean)

    fee_variance = next(
        (r for r in results if r.rate_variance and r.rate_variance.rule == "FEE_VARIANCE"), None
    )
    if fee_variance:
        print("--- Example: FEE_VARIANCE ---")
        print_waterfall(fee_variance)

    gst_variance = next(
        (r for r in results if r.rate_variance and r.rate_variance.rule == "GST_ON_MDR_VARIANCE"),
        None,
    )
    if gst_variance:
        print("--- Example: GST_ON_MDR_VARIANCE ---")
        print_waterfall(gst_variance)


if __name__ == "__main__":
    main()
