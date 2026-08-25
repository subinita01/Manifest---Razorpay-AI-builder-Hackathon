import json
from decimal import Decimal
from pathlib import Path

import pytest

from data.generator import generate

SEED = 7
N_ORDERS = 600


def test_same_seed_produces_byte_identical_files(tmp_path: Path):
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    generate(seed=SEED, n_orders=N_ORDERS, out_dir=out_a)
    generate(seed=SEED, n_orders=N_ORDERS, out_dir=out_b)

    for name in [
        "bank_statement.csv",
        "settlement_batch.csv",
        "internal_ledger.csv",
        "ground_truth.json",
    ]:
        assert (out_a / name).read_bytes() == (out_b / name).read_bytes(), name


def test_ground_truth_lists_every_planted_defect(tmp_path: Path):
    out_dir = tmp_path / "demo"
    generate(seed=SEED, n_orders=N_ORDERS, out_dir=out_dir)
    ground_truth = json.loads((out_dir / "ground_truth.json").read_text())

    labels = [e["true_label"] for e in ground_truth["planted_exceptions"]]
    expected_counts = {
        "FEE_VARIANCE": 3,
        "GST_ON_MDR_VARIANCE": 2,
        "TDS_CODE_MIGRATION_BREAK": 11,
        "TDS_AMOUNT_MISMATCH": 4,
        "TIMING_T_PLUS_N": 5,
        "BANK_ONLY": 2,
        "LEDGER_ONLY": 3,
        "ROUNDING": 6,
    }
    for label, count in expected_counts.items():
        assert labels.count(label) == count, label

    assert len(ground_truth["unresolvable_by_design"]) == 3


def test_core_never_imports_ground_truth():
    core_dir = Path(__file__).resolve().parent.parent / "core"
    offenders = [
        path
        for path in core_dir.rglob("*.py")
        if "ground_truth" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"core/ must never reference ground_truth: {offenders}"


def test_generated_csvs_have_no_float_literals_for_money(tmp_path: Path):
    out_dir = tmp_path / "demo"
    generate(seed=SEED, n_orders=N_ORDERS, out_dir=out_dir)
    bank_csv = (out_dir / "bank_statement.csv").read_text()
    assert "e-" not in bank_csv.lower(), "scientific notation would indicate float leakage"


def test_rounding_residuals_exceed_stage1_tolerance(tmp_path: Path):
    """A ROUNDING residual at or below core.models.TOLERANCE would be silently
    absorbed by Stage 1's amount check, making the planted defect invisible
    to the rest of the pipeline instead of reaching Stage 2 for attribution.
    """
    from core.models import TOLERANCE

    out_dir = tmp_path / "demo"
    generate(seed=SEED, n_orders=N_ORDERS, out_dir=out_dir)
    ground_truth = json.loads((out_dir / "ground_truth.json").read_text())
    for e in ground_truth["planted_exceptions"]:
        if e["true_label"] == "ROUNDING":
            assert Decimal(e["amount_impact"]) > TOLERANCE, e["id"]


def _load_demo_csvs(out_dir: Path):
    import csv

    with (out_dir / "bank_statement.csv").open() as f:
        bank = list(csv.DictReader(f))
    with (out_dir / "settlement_batch.csv").open() as f:
        settlement = list(csv.DictReader(f))
    return bank, settlement


def _settlement_net(rows) -> Decimal:
    total = Decimal("0")
    for r in rows:
        amt, fee, tax = Decimal(r["amount"]), Decimal(r["fee"]), Decimal(r["tax"])
        if r["type"] == "payment" and r["on_hold"] != "True":
            total += amt - fee - tax
        elif r["type"] in ("refund", "adjustment"):
            total += amt
    return total


@pytest.mark.parametrize("seed", [1, 7, 42, 123, 999])
def test_ground_truth_is_internally_consistent_with_csvs(tmp_path: Path, seed: int):
    """Regression test for two generator bugs found by manual cross-checking:

    1. A batch-level defect's settlement_ids list could reference a
       settlement_id that a later defect-planting pass deleted, because
       LEDGER_ONLY used to delete settlement rows *after* other batches'
       ground-truth entries already referenced them.
    2. settlement_ids lists omitted refund/chargeback rows sharing the same
       UTR, understating the batch's true net.

    Neither was caught by count-only assertions -- both required rebuilding
    each entry's numbers independently from the raw CSVs and comparing.
    """
    out_dir = tmp_path / f"demo_{seed}"
    generate(seed=seed, n_orders=N_ORDERS, out_dir=out_dir)
    bank, settlement = _load_demo_csvs(out_dir)
    settlement_by_id = {r["settlement_id"]: r for r in settlement}
    ground_truth = json.loads((out_dir / "ground_truth.json").read_text())

    for m in ground_truth["expected_matches"]:
        rows = [settlement_by_id[sid] for sid in m["settlement_ids"]]
        credit = Decimal(bank[m["bank_row_id"]]["credit"])
        assert abs(credit - _settlement_net(rows)) <= Decimal("0.01"), m["bank_row_id"]

    accounted_bank_ids = {m["bank_row_id"] for m in ground_truth["expected_matches"]}
    for e in ground_truth["planted_exceptions"]:
        for sid in e.get("settlement_ids", []):
            assert sid in settlement_by_id, f"{e['id']} references missing {sid}"
        if "bank_row_id" in e:
            accounted_bank_ids.add(e["bank_row_id"])
    for u in ground_truth["unresolvable_by_design"]:
        accounted_bank_ids.add(u["bank_row_id"])

    assert accounted_bank_ids == set(
        range(len(bank))
    ), "every bank row must have a ground-truth entry"
