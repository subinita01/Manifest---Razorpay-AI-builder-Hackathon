"""Seeded synthetic dataset generator for MANIFEST.

Produces bank_statement.csv, settlement_batch.csv, internal_ledger.csv, and
ground_truth.json for a given seed. Every planted defect is recorded in
ground_truth.json with its true label so the evaluation harness (evaluation/)
can score the matching cascade against a known answer.

This module is developed and reviewed separately from the matching cascade in
core/matching/ and is never tuned to make the matcher look good. It has no
dependency on core/ or on the matcher's attribution logic.

Note on batch sizing: the product brief describes settlement batches of
50-250 orders. At the demo scale (600 orders) that range cannot fit the
number of distinct batch-level planted defects this generator needs (16
batches minimum) while leaving any clean batches, so batch size here is
scaled down to 8-30 orders. The realism property this preserves -- one bank
credit corresponds to many orders -- still holds; only the literal range
differs from the brief.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

CENT = Decimal("0.01")
MDR_RATE = Decimal("0.02")
MDR_RATE_VARIANT = Decimal("0.024")
GST_RATE = Decimal("0.18")
GST_RATE_VARIANT = Decimal("0.17")
TDS_CUTOVER = date(2026, 4, 1)
BATCH_SIZE_RANGE = (8, 30)
OPENING_BALANCE = Decimal("2000000.00")

# Independent restatement of config/tds_code_map.yaml's placeholder mapping.
# Kept separate on purpose: the generator must not import core/config, so a
# matcher bug in the config loader can never silently "fix itself" here.
LEGACY_TO_NEW_CODE = {
    "194C": "1023",
    "194J": "1026",
    "194I": "1028",
    "194H": "1031",
    "194A": "1034",
}

# Independent restatement of config/tds_rates.yaml's placeholder schedule.
# Rate depends on the code AND whether the vendor has a PAN on file -- using
# a single flat rate here would make Stage 4's per-code rate check false-
# positive on every "correct" TDS row for a code whose contracted rate isn't
# that flat value.
RATE_WITH_PAN = {
    "1023": Decimal("0.01"),
    "1026": Decimal("0.10"),
    "1028": Decimal("0.10"),
    "1031": Decimal("0.05"),
    "1034": Decimal("0.10"),
}
RATE_WITHOUT_PAN = {code: Decimal("0.20") for code in RATE_WITH_PAN}


def _tds_rate_for(new_code: str, has_pan: bool) -> Decimal:
    table = RATE_WITH_PAN if has_pan else RATE_WITHOUT_PAN
    return table[new_code]


METHODS = ["UPI", "NEFT", "RTGS", "CARD"]
CARD_NETWORKS = ["VISA", "MASTERCARD", "RUPAY"]

NARRATION_TEMPLATES = [
    "NEFT CR-RAZORPAY SOFTWARE PVT LTD-UTR{utr}-STL",
    "RTGS/{utr}/RAZORPAY/SETTLEMENT",
    "UPI-SETTLEMENT-{utr}",
]


def _q(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _fmt_date_iso(d: date) -> str:
    return d.isoformat()


def _fmt_date_slash(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _fmt_date_mon(d: date) -> str:
    return d.strftime("%d-%b-%y")


DATE_FORMATTERS = [_fmt_date_iso, _fmt_date_slash, _fmt_date_mon]


def _random_utr(rng: random.Random) -> str:
    return "".join(rng.choice("0123456789") for _ in range(16))


@dataclass
class Order:
    order_id: str
    payment_id: str
    amount: Decimal
    created_at: date
    method: str


@dataclass
class GeneratorState:
    rng: random.Random
    orders: list[Order] = field(default_factory=list)
    bank_rows: list[dict[str, Any]] = field(default_factory=list)
    settlement_rows: list[dict[str, Any]] = field(default_factory=list)
    ledger_rows: list[dict[str, Any]] = field(default_factory=list)
    expected_matches: list[dict[str, Any]] = field(default_factory=list)
    planted_exceptions: list[dict[str, Any]] = field(default_factory=list)
    unresolvable_by_design: list[dict[str, Any]] = field(default_factory=list)
    balance: Decimal = OPENING_BALANCE


def _make_orders(state: GeneratorState, n_orders: int) -> None:
    start = TDS_CUTOVER - timedelta(days=60)
    span_days = 120
    for i in range(n_orders):
        offset = state.rng.randint(0, span_days)
        created_at = start + timedelta(days=offset)
        amount = _q(Decimal(state.rng.randint(50000, 5000000)) / Decimal(100))
        state.orders.append(
            Order(
                order_id=f"ord_{i:05d}",
                payment_id=f"pay_{i:05d}",
                amount=amount,
                created_at=created_at,
                method=state.rng.choice(METHODS),
            )
        )
    state.orders.sort(key=lambda o: o.created_at)


def _chunk_into_batches(state: GeneratorState) -> list[list[Order]]:
    batches: list[list[Order]] = []
    i = 0
    orders = state.orders
    while i < len(orders):
        size = state.rng.randint(*BATCH_SIZE_RANGE)
        batches.append(orders[i : i + size])
        i += size
    return batches


def _tds_fields_for_order(state: GeneratorState, order: Order, has_pan: bool) -> dict[str, Any]:
    """Return the *correct* TDS fields for an order, before any defect is planted."""
    if state.rng.random() >= 0.30:
        return {
            "tds_section_legacy": None,
            "tds_code_new": None,
            "tds_amount": Decimal("0"),
        }
    legacy = state.rng.choice(list(LEGACY_TO_NEW_CODE))
    new_code = LEGACY_TO_NEW_CODE[legacy]
    rate = _tds_rate_for(new_code, has_pan)
    tds_amount = _q(order.amount * rate)
    if order.created_at >= TDS_CUTOVER:
        return {
            "tds_section_legacy": None,
            "tds_code_new": new_code,
            "tds_amount": tds_amount,
            "_legacy_for_defects": legacy,
        }
    return {
        "tds_section_legacy": legacy,
        "tds_code_new": None,
        "tds_amount": tds_amount,
        "_legacy_for_defects": legacy,
    }


def _build_ledger(state: GeneratorState) -> None:
    for idx, order in enumerate(state.orders):
        has_pan = idx % 3 != 0
        tds = _tds_fields_for_order(state, order, has_pan)
        tds.pop("_legacy_for_defects", None)
        state.ledger_rows.append(
            {
                "order_id": order.order_id,
                "invoice_no": f"INV-{10000 + idx}",
                "gross_amount": order.amount,
                "tds_section_legacy": tds["tds_section_legacy"],
                "tds_code_new": tds["tds_code_new"],
                "tds_amount": tds["tds_amount"],
                "gst_rate": Decimal("18.00"),
                "vendor_pan_masked": f"ABCP{1000 + idx}Z" if has_pan else "PANNOTAVAIL",
                "posted_at": datetime.combine(order.created_at, datetime.min.time()).isoformat(),
            }
        )


def _plant_tds_defects(state: GeneratorState) -> None:
    """Corrupt a subset of already-written ledger rows to simulate the
    FY2026-27 code migration break and amount mismatches."""
    post_cutover = [row for row in state.ledger_rows if row["posted_at"] >= TDS_CUTOVER.isoformat()]

    # 8 orders posted after cutover that carry ONLY the legacy section
    # (migration never populated the new code).
    candidates = [
        row for row in post_cutover if row["tds_code_new"] is None and row["tds_amount"] == 0
    ]
    rng_sample = state.rng.sample(candidates, k=min(8, len(candidates)))
    for row in rng_sample:
        legacy = state.rng.choice(list(LEGACY_TO_NEW_CODE))
        has_pan = row["vendor_pan_masked"] != "PANNOTAVAIL"
        rate = _tds_rate_for(LEGACY_TO_NEW_CODE[legacy], has_pan)
        gross = row["gross_amount"]
        row["tds_section_legacy"] = legacy
        row["tds_code_new"] = None
        row["tds_amount"] = _q(gross * rate)
        state.planted_exceptions.append(
            {
                "id": f"tds_migration_break_{row['order_id']}",
                "true_label": "TDS_CODE_MIGRATION_BREAK",
                "order_ids": [row["order_id"]],
                "amount_impact": str(row["tds_amount"]),
                "detail": "posted after cutover with legacy section only, no new code",
            }
        )

    # 3 orders where legacy and new codes are both present but contradict
    # the mapping.
    remaining = [row for row in post_cutover if row not in rng_sample]
    contradiction_rows = state.rng.sample(remaining, k=min(3, len(remaining)))
    for row in contradiction_rows:
        legacy = state.rng.choice(list(LEGACY_TO_NEW_CODE))
        correct_new_code = LEGACY_TO_NEW_CODE[legacy]
        wrong_code = state.rng.choice(
            [c for c in LEGACY_TO_NEW_CODE.values() if c != correct_new_code]
        )
        has_pan = row["vendor_pan_masked"] != "PANNOTAVAIL"
        rate = _tds_rate_for(correct_new_code, has_pan)
        gross = row["gross_amount"]
        row["tds_section_legacy"] = legacy
        row["tds_code_new"] = wrong_code
        row["tds_amount"] = _q(gross * rate)
        state.planted_exceptions.append(
            {
                "id": f"tds_contradiction_{row['order_id']}",
                "true_label": "TDS_CODE_MIGRATION_BREAK",
                "order_ids": [row["order_id"]],
                "amount_impact": str(row["tds_amount"]),
                "detail": (
                    f"legacy {legacy} maps to {correct_new_code} but row carries {wrong_code}"
                ),
            }
        )

    # 4 orders where the deducted TDS amount does not equal rate * gross.
    with_tds = [
        row
        for row in state.ledger_rows
        if row["tds_amount"] > 0 and row not in rng_sample and row not in contradiction_rows
    ]
    mismatch_rows = state.rng.sample(with_tds, k=min(4, len(with_tds)))
    for row in mismatch_rows:
        drift = Decimal(state.rng.choice([-500, -250, 250, 500, 750])) / Decimal(100)
        row["tds_amount"] = _q(row["tds_amount"] + drift)
        state.planted_exceptions.append(
            {
                "id": f"tds_amount_mismatch_{row['order_id']}",
                "true_label": "TDS_AMOUNT_MISMATCH",
                "order_ids": [row["order_id"]],
                "amount_impact": str(abs(drift)),
                "detail": "deducted TDS does not equal rate * gross_amount",
            }
        )


def _build_settlement_and_bank(state: GeneratorState, batches: list[list[Order]]) -> None:
    n_batches = len(batches)
    order_indices = list(range(n_batches))
    state.rng.shuffle(order_indices)

    needed = {
        "FEE_VARIANCE": 3,
        "GST_ON_MDR_VARIANCE": 2,
        "TIMING_T_PLUS_N": 5,
        "ROUNDING": 6,
    }
    total_needed = sum(needed.values())
    if n_batches < total_needed:
        raise ValueError(
            f"Not enough batches ({n_batches}) for planted defects ({total_needed}); "
            "increase --orders."
        )

    assignment: dict[int, str] = {}
    cursor = 0
    for label, count in needed.items():
        for _ in range(count):
            assignment[order_indices[cursor]] = label
            cursor += 1

    for b_idx, batch in enumerate(batches):
        label = assignment.get(b_idx)
        settlement_utr = _random_utr(state.rng)
        mdr_rate = MDR_RATE_VARIANT if label == "FEE_VARIANCE" else MDR_RATE
        gst_rate = GST_RATE_VARIANT if label == "GST_ON_MDR_VARIANCE" else GST_RATE

        last_order_date = batch[-1].created_at
        settled_at = datetime.combine(
            last_order_date + timedelta(days=1), datetime.min.time()
        ).replace(hour=12)

        actual_net = Decimal("0")
        settlement_ids_for_batch: list[str] = []
        order_ids_for_batch: list[str] = []
        batch_gross = Decimal("0")
        batch_fee = Decimal("0")
        batch_tax = Decimal("0")

        for o_idx, order in enumerate(batch):
            settlement_id = f"setl_{b_idx:04d}_{o_idx:03d}"
            fee = _q(order.amount * mdr_rate)
            tax = _q(fee * gst_rate)
            on_hold = state.rng.random() < 0.03
            card_network = state.rng.choice(CARD_NETWORKS) if order.method == "CARD" else None
            batch_gross += order.amount
            batch_fee += fee
            batch_tax += tax

            state.settlement_rows.append(
                {
                    "settlement_id": settlement_id,
                    "settlement_utr": settlement_utr,
                    "entity_id": "ent_001",
                    "type": "payment",
                    "amount": order.amount,
                    "fee": fee,
                    "tax": tax,
                    "on_hold": on_hold,
                    "settled": True,
                    "created_at": datetime.combine(
                        order.created_at, datetime.min.time()
                    ).isoformat(),
                    "settled_at": settled_at.isoformat(),
                    "payment_id": order.payment_id,
                    "order_id": order.order_id,
                    "dispute_id": None,
                    "method": order.method,
                    "card_network": card_network,
                }
            )
            settlement_ids_for_batch.append(settlement_id)
            order_ids_for_batch.append(order.order_id)

            if not on_hold:
                actual_net += order.amount - fee - tax

            if state.rng.random() < 0.05:
                refund_amount = _q(order.amount * Decimal(state.rng.choice([25, 50, 100])) / 100)
                state.settlement_rows.append(
                    {
                        "settlement_id": f"{settlement_id}_rf",
                        "settlement_utr": settlement_utr,
                        "entity_id": "ent_001",
                        "type": "refund",
                        "amount": -refund_amount,
                        "fee": Decimal("0"),
                        "tax": Decimal("0"),
                        "on_hold": False,
                        "settled": True,
                        "created_at": datetime.combine(
                            order.created_at, datetime.min.time()
                        ).isoformat(),
                        "settled_at": settled_at.isoformat(),
                        "payment_id": order.payment_id,
                        "order_id": order.order_id,
                        "dispute_id": None,
                        "method": order.method,
                        "card_network": card_network,
                    }
                )
                settlement_ids_for_batch.append(f"{settlement_id}_rf")
                actual_net -= refund_amount

            if state.rng.random() < 0.01:
                chargeback_amount = _q(order.amount * Decimal("0.5"))
                state.settlement_rows.append(
                    {
                        "settlement_id": f"{settlement_id}_cb",
                        "settlement_utr": settlement_utr,
                        "entity_id": "ent_001",
                        "type": "adjustment",
                        "amount": -chargeback_amount,
                        "fee": Decimal("0"),
                        "tax": Decimal("0"),
                        "on_hold": False,
                        "settled": True,
                        "created_at": datetime.combine(
                            order.created_at, datetime.min.time()
                        ).isoformat(),
                        "settled_at": settled_at.isoformat(),
                        "payment_id": order.payment_id,
                        "order_id": order.order_id,
                        "dispute_id": f"disp_{b_idx:04d}_{o_idx:03d}",
                        "method": order.method,
                        "card_network": card_network,
                    }
                )
                settlement_ids_for_batch.append(f"{settlement_id}_cb")
                actual_net -= chargeback_amount

        bank_credit = actual_net
        residual_note = None
        if label == "ROUNDING":
            # Must stay strictly greater than core.models.TOLERANCE (0.01) or
            # Stage 1's amount check silently absorbs it as a clean match,
            # making the planted defect invisible to the pipeline.
            drift = Decimal(state.rng.choice([-9, -7, -5, -3, 3, 5, 7, 9])) / Decimal(100)
            bank_credit = _q(bank_credit + drift)
            residual_note = str(abs(drift))

        txn_date = settled_at.date()
        if label == "TIMING_T_PLUS_N":
            txn_date = txn_date + timedelta(days=3)

        fmt = DATE_FORMATTERS[b_idx % len(DATE_FORMATTERS)]
        truncate_utr = state.rng.random() < 0.10
        narration_utr = settlement_utr[:8] if truncate_utr else settlement_utr
        narration = state.rng.choice(NARRATION_TEMPLATES).format(utr=narration_utr)

        state.balance += bank_credit
        bank_row_id = len(state.bank_rows)
        state.bank_rows.append(
            {
                "txn_date": fmt(txn_date),
                "value_date": fmt(txn_date),
                "narration": narration,
                "ref_no": settlement_utr,
                "debit": Decimal("0"),
                "credit": bank_credit,
                "balance": state.balance,
            }
        )

        if label == "FEE_VARIANCE":
            contracted_fee = _q(batch_gross * MDR_RATE)
            state.planted_exceptions.append(
                {
                    "id": f"{label.lower()}_{settlement_utr}",
                    "true_label": label,
                    "settlement_ids": settlement_ids_for_batch,
                    "bank_row_id": bank_row_id,
                    "amount_impact": str(_q(batch_fee - contracted_fee)),
                    "detail": f"implied_rate={mdr_rate}",
                }
            )
        elif label == "GST_ON_MDR_VARIANCE":
            contracted_tax = _q(batch_fee * GST_RATE)
            state.planted_exceptions.append(
                {
                    "id": f"{label.lower()}_{settlement_utr}",
                    "true_label": label,
                    "settlement_ids": settlement_ids_for_batch,
                    "bank_row_id": bank_row_id,
                    "amount_impact": str(_q(contracted_tax - batch_tax)),
                    "detail": f"implied_rate={gst_rate}",
                }
            )
        elif label == "TIMING_T_PLUS_N":
            state.planted_exceptions.append(
                {
                    "id": f"timing_{settlement_utr}",
                    "true_label": "TIMING_T_PLUS_N",
                    "settlement_ids": settlement_ids_for_batch,
                    "bank_row_id": bank_row_id,
                    "amount_impact": "0.00",
                    "detail": "bank credit landed 3 days after settled_at",
                }
            )
        elif label == "ROUNDING":
            state.planted_exceptions.append(
                {
                    "id": f"rounding_{settlement_utr}",
                    "true_label": "ROUNDING",
                    "settlement_ids": settlement_ids_for_batch,
                    "bank_row_id": bank_row_id,
                    "amount_impact": residual_note,
                    "detail": "sub-rupee residual between bridge and bank credit",
                }
            )
        else:
            state.expected_matches.append(
                {
                    "bank_row_id": bank_row_id,
                    "settlement_utr": settlement_utr,
                    "settlement_ids": settlement_ids_for_batch,
                    "order_ids": order_ids_for_batch,
                }
            )


def _plant_bank_only(state: GeneratorState) -> None:
    for i in range(2):
        utr = _random_utr(state.rng)
        amount = _q(Decimal(state.rng.randint(10000, 500000)) / 100)
        state.balance += amount
        bank_row_id = len(state.bank_rows)
        state.bank_rows.append(
            {
                "txn_date": TDS_CUTOVER.isoformat(),
                "value_date": TDS_CUTOVER.isoformat(),
                "narration": f"NEFT CR-UNKNOWN COUNTERPARTY-UTR{utr}-STL",
                "ref_no": utr,
                "debit": Decimal("0"),
                "credit": amount,
                "balance": state.balance,
            }
        )
        state.planted_exceptions.append(
            {
                "id": f"bank_only_{i:02d}",
                "true_label": "BANK_ONLY",
                "bank_row_id": bank_row_id,
                "amount_impact": str(amount),
                "detail": "unexplained bank credit with no matching settlement",
            }
        )


def _plant_ledger_only(state: GeneratorState) -> None:
    """Remove 3 orders from the settlement pipeline entirely, before batching,
    so their ledger row has no corresponding settlement. This must run before
    _chunk_into_batches/_build_settlement_and_bank: removing a settlement row
    *after* a batch's ground-truth entry is recorded would leave that entry's
    settlement_ids pointing at a row that no longer exists.
    """
    victims = state.rng.sample(state.orders, k=min(3, len(state.orders)))
    victim_ids = {o.order_id for o in victims}
    state.orders = [o for o in state.orders if o.order_id not in victim_ids]
    for order in victims:
        state.planted_exceptions.append(
            {
                "id": f"ledger_only_{order.order_id}",
                "true_label": "LEDGER_ONLY",
                "order_ids": [order.order_id],
                "amount_impact": str(order.amount),
                "detail": "order posted to ledger but never settled",
            }
        )


def _plant_unresolvable(state: GeneratorState) -> None:
    for i in range(3):
        shared_amount = _q(Decimal(state.rng.randint(500000, 2000000)) / 100)
        utr_a = _random_utr(state.rng)
        utr_b = _random_utr(state.rng)
        d = TDS_CUTOVER + timedelta(days=i)
        created_at = datetime.combine(d, datetime.min.time())

        for suffix, utr in (("a", utr_a), ("b", utr_b)):
            oid = f"ord_unresolvable_{i:02d}_{suffix}"
            settlement_id = f"setl_unresolvable_{i:02d}_{suffix}"
            fee = _q(shared_amount * MDR_RATE)
            tax = _q(fee * GST_RATE)
            state.settlement_rows.append(
                {
                    "settlement_id": settlement_id,
                    "settlement_utr": utr,
                    "entity_id": "ent_001",
                    "type": "payment",
                    "amount": shared_amount,
                    "fee": fee,
                    "tax": tax,
                    "on_hold": False,
                    "settled": True,
                    "created_at": created_at.isoformat(),
                    "settled_at": created_at.isoformat(),
                    "payment_id": f"pay_unresolvable_{i:02d}_{suffix}",
                    "order_id": oid,
                    "dispute_id": None,
                    "method": "NEFT",
                    "card_network": None,
                }
            )

        net = (
            shared_amount
            - _q(shared_amount * MDR_RATE)
            - _q(_q(shared_amount * MDR_RATE) * GST_RATE)
        )
        truncated = utr_a[:6]
        narration = f"NEFT CR-RAZORPAY SOFTWARE PVT LTD-UTR{truncated}-STL"
        state.balance += net
        bank_row_id = len(state.bank_rows)
        state.bank_rows.append(
            {
                "txn_date": d.isoformat(),
                "value_date": d.isoformat(),
                "narration": narration,
                "ref_no": truncated,
                "debit": Decimal("0"),
                "credit": net,
                "balance": state.balance,
            }
        )
        state.unresolvable_by_design.append(
            {
                "id": f"unresolvable_{i:02d}",
                "bank_row_id": bank_row_id,
                "candidate_settlement_utrs": [utr_a, utr_b],
                "reason": (
                    "narration UTR truncated to a prefix shared by two settlements with "
                    "identical net amount; no information in the data can disambiguate them"
                ),
            }
        )


def generate(seed: int, n_orders: int, out_dir: Path) -> None:
    rng = random.Random(seed)
    state = GeneratorState(rng=rng)

    _make_orders(state, n_orders)
    _build_ledger(state)
    _plant_tds_defects(state)
    _plant_ledger_only(state)

    batches = _chunk_into_batches(state)
    _build_settlement_and_bank(state, batches)
    _plant_bank_only(state)
    _plant_unresolvable(state)

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_bank_csv(out_dir / "bank_statement.csv", state.bank_rows)
    _write_settlement_csv(out_dir / "settlement_batch.csv", state.settlement_rows)
    _write_ledger_csv(out_dir / "internal_ledger.csv", state.ledger_rows)
    _write_ground_truth(
        out_dir / "ground_truth.json",
        seed=seed,
        n_orders=n_orders,
        state=state,
    )


def _write_bank_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = ["txn_date", "value_date", "narration", "ref_no", "debit", "credit", "balance"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in fieldnames})


def _write_settlement_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "settlement_id",
        "settlement_utr",
        "entity_id",
        "type",
        "amount",
        "fee",
        "tax",
        "on_hold",
        "settled",
        "created_at",
        "settled_at",
        "payment_id",
        "order_id",
        "dispute_id",
        "method",
        "card_network",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            out = {k: row.get(k) for k in fieldnames}
            out["on_hold"] = str(out["on_hold"])
            out["settled"] = str(out["settled"])
            writer.writerow(out)


def _write_ledger_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "order_id",
        "invoice_no",
        "gross_amount",
        "tds_section_legacy",
        "tds_code_new",
        "tds_amount",
        "gst_rate",
        "vendor_pan_masked",
        "posted_at",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in fieldnames})


def _write_ground_truth(path: Path, seed: int, n_orders: int, state: GeneratorState) -> None:
    payload = {
        "run_seed": seed,
        "n_orders": n_orders,
        "expected_matches": state.expected_matches,
        "planted_exceptions": state.planted_exceptions,
        "unresolvable_by_design": state.unresolvable_by_design,
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, default=str)
        handle.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a seeded MANIFEST demo dataset.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--orders", type=int, default=600)
    parser.add_argument("--out", type=Path, default=Path("data/demo"))
    args = parser.parse_args()
    generate(seed=args.seed, n_orders=args.orders, out_dir=args.out)
    print(f"Generated dataset (seed={args.seed}, orders={args.orders}) at {args.out}")


if __name__ == "__main__":
    main()
