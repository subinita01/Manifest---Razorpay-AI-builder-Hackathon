from datetime import datetime
from decimal import Decimal
from pathlib import Path

from backend.db import (
    find_run_by_idempotency_key,
    get_bridge,
    get_connection,
    get_exceptions,
    get_run,
    save_run,
)
from core.matching.stage2_bridge import BridgeFinding, BridgeResult, BridgeStep
from core.models import Exception_, MatchResult, RunManifest
from core.pipeline import RunResult


def _manifest(run_id="run_1"):
    return RunManifest(
        run_id=run_id,
        seed=42,
        git_sha="abc123",
        config_hash="cfg123",
        model_string=None,
        library_versions={"pydantic": "2.8.2"},
        created_at=datetime(2026, 8, 23, 12, 0, 0),
    )


def _result():
    return RunResult(
        matched=[
            MatchResult(
                match_id="m1",
                stage_name="stage1_utr",
                bank_row_id="0",
                settlement_row_id="utr1",
                confidence=1.0,
                detail={"settlement_ids": ["s1"]},
            )
        ],
        needs_review=[],
        exceptions=[
            Exception_(
                exception_id="exc1",
                taxonomy_code="BANK_ONLY",
                severity="WARN",
                row_ids=["3"],
                amount_impact=Decimal("500.00"),
                detail={"bank_row_id": 3},
            )
        ],
        bridges={
            "utr1": BridgeResult(
                settlement_utr="utr1",
                steps=[BridgeStep("Gross", Decimal("1000.00"), Decimal("1000.00"), ["s1"])],
                expected_net=Decimal("976.40"),
                bank_credit=Decimal("976.40"),
                residual=Decimal("0.00"),
                closed=True,
                attribution=None,
                rate_variance=BridgeFinding("FEE_VARIANCE", {"implied_rate": "0.024"}),
            )
        },
        total_input_rows=2,
        matched_row_count=1,
        needs_review_row_count=0,
        exception_row_count=1,
    )


def test_save_and_retrieve_a_run(tmp_path: Path):
    conn = get_connection(tmp_path / "test.duckdb")
    manifest = _manifest()
    save_run(
        conn,
        manifest,
        _result(),
        dataset_id="demo",
        use_llm=False,
        fuzzy_threshold=Decimal("0.90"),
        idempotency_key="key1",
    )

    stored = get_run(conn, "run_1")
    assert stored["run_id"] == "run_1"
    assert stored["seed"] == 42
    assert stored["total_input_rows"] == 2

    exceptions = get_exceptions(conn, "run_1")
    assert len(exceptions) == 1
    assert exceptions[0]["taxonomy_code"] == "BANK_ONLY"
    assert Decimal(exceptions[0]["amount_impact"]) == Decimal("500.00")

    bridge = get_bridge(conn, "run_1", "utr1")
    assert bridge["closed"] is True
    assert bridge["rate_variance"]["rule"] == "FEE_VARIANCE"
    assert Decimal(bridge["expected_net"]) == Decimal("976.40")


def test_idempotency_key_lookup(tmp_path: Path):
    conn = get_connection(tmp_path / "test.duckdb")
    save_run(
        conn,
        _manifest(),
        _result(),
        dataset_id="demo",
        use_llm=False,
        fuzzy_threshold=Decimal("0.90"),
        idempotency_key="same-key",
    )
    assert find_run_by_idempotency_key(conn, "same-key") == "run_1"
    assert find_run_by_idempotency_key(conn, "different-key") is None


def test_get_run_returns_none_for_unknown_run(tmp_path: Path):
    conn = get_connection(tmp_path / "test.duckdb")
    assert get_run(conn, "does-not-exist") is None


def test_money_columns_are_decimal_not_real(tmp_path: Path):
    conn = get_connection(tmp_path / "test.duckdb")
    save_run(
        conn,
        _manifest(),
        _result(),
        dataset_id="demo",
        use_llm=False,
        fuzzy_threshold=Decimal("0.90"),
        idempotency_key="key1",
    )
    column_types = {row[0]: row[1] for row in conn.execute("DESCRIBE exceptions").fetchall()}
    assert "DECIMAL" in column_types["amount_impact"]
    assert column_types["amount_impact"] != "REAL"
