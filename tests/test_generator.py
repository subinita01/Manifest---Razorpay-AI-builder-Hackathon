import json
from pathlib import Path

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
