from datetime import datetime
from decimal import Decimal
from pathlib import Path

from backend.db import (
    find_run_by_idempotency_key,
    get_bridge,
    get_bridge_utrs,
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

    utrs = get_bridge_utrs(conn, "run_1")
    assert utrs == [
        {
            "settlement_utr": "utr1",
            "closed": True,
            "attribution_rule": None,
            "rate_variance_rule": "FEE_VARIANCE",
        }
    ]


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


class _FlakyConnection:
    """Wraps a real connection and raises on its Nth .execute() call --
    simulates a crash partway through save_run's multi-statement write
    (a serialization error, a dropped connection, a full disk)."""

    def __init__(self, real_conn, fail_on_call: int):
        self._real = real_conn
        self._call_count = 0
        self._fail_on_call = fail_on_call

    def execute(self, sql, params=None):
        self._call_count += 1
        if self._call_count == self._fail_on_call:
            raise RuntimeError(f"simulated crash on execute() call #{self._fail_on_call}")
        return self._real.execute(sql, params)


def test_save_run_rolls_back_completely_on_a_mid_write_failure(tmp_path: Path):
    """Regression test for a real gap: without an explicit transaction,
    a crash between the runs INSERT and the exceptions INSERT used to
    leave a runs row claiming exception_row_count=1 with zero actual rows
    in the exceptions table -- a silent partial write directly
    contradicting CLAUDE.md rule 6 (nothing silently dropped). Call
    sequence inside save_run is: BEGIN(1), INSERT runs(2), INSERT
    matches(3), INSERT exceptions(4) -- failing on call 4 proves the
    already-applied runs and matches inserts get rolled back too, not
    just that the exceptions insert itself never happens."""
    conn = get_connection(tmp_path / "test.duckdb")
    flaky = _FlakyConnection(conn, fail_on_call=4)

    try:
        save_run(
            flaky,
            _manifest(),
            _result(),
            dataset_id="demo",
            use_llm=False,
            fuzzy_threshold=Decimal("0.90"),
            idempotency_key="key1",
        )
        raise AssertionError("expected save_run to propagate the simulated failure")
    except RuntimeError as exc:
        assert "simulated crash" in str(exc)

    # Query the real, underlying connection directly -- nothing from the
    # failed write should have survived in any of the four tables.
    assert get_run(conn, "run_1") is None
    assert get_exceptions(conn, "run_1") == []
    assert (
        conn.execute("SELECT COUNT(*) FROM matches WHERE run_id = ?", ["run_1"]).fetchone()[0] == 0
    )
    assert get_bridge_utrs(conn, "run_1") == []
