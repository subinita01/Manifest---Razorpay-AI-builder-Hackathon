"""Pure unit tests (no Postgres needed) plus integration tests that only
run when a real Postgres is reachable via DATABASE_URL -- self-skipping
locally, exercised for real in CI's postgres service (see
.github/workflows/ci.yml).
"""

from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal

import pytest

from backend.db import (
    find_run_by_idempotency_key,
    get_bridge,
    get_bridge_utrs,
    get_exceptions,
    save_run,
)
from backend.db import get_run as db_get_run
from backend.db_postgres import (
    PlaceholderMismatch,
    build_postgres_connection,
    translate_placeholders,
)
from core.matching.stage2_bridge import BridgeFinding, BridgeResult, BridgeStep
from core.models import Exception_, MatchResult, RunManifest
from core.pipeline import RunResult


def test_translate_placeholders_rewrites_qmark_to_pyformat():
    sql, params = translate_placeholders("SELECT * FROM runs WHERE run_id = ?", ["r1"])
    assert sql == "SELECT * FROM runs WHERE run_id = %s"
    assert params == ["r1"]


def test_translate_placeholders_handles_multiple_placeholders():
    sql, params = translate_placeholders("INSERT INTO t VALUES (?, ?, ?)", [1, "a", True])
    assert sql == "INSERT INTO t VALUES (%s, %s, %s)"
    assert params == [1, "a", True]


def test_translate_placeholders_handles_zero_placeholders():
    sql, params = translate_placeholders("SELECT 1", None)
    assert sql == "SELECT 1"
    assert params == []


def test_translate_placeholders_raises_on_count_mismatch():
    with pytest.raises(PlaceholderMismatch):
        translate_placeholders("SELECT * FROM runs WHERE run_id = ?", ["r1", "extra"])
    with pytest.raises(PlaceholderMismatch):
        translate_placeholders("SELECT * FROM runs WHERE run_id = ? AND seed = ?", ["r1"])


# --- Integration tests against a real Postgres -----------------------------


def _postgres_reachable(database_url: str) -> bool:
    try:
        import psycopg

        with psycopg.connect(database_url, connect_timeout=2):
            return True
    except Exception:
        return False


_DATABASE_URL = os.environ.get("DATABASE_URL", "")
_SKIP_REASON = "DATABASE_URL not set or Postgres not reachable -- set DATABASE_URL to run this"
_SKIP = not _DATABASE_URL or not _postgres_reachable(_DATABASE_URL)


def _manifest(run_id="pg_run_1"):
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


@pytest.mark.skipif(_SKIP, reason=_SKIP_REASON)
def test_save_and_retrieve_a_run_against_real_postgres():
    conn = build_postgres_connection(_DATABASE_URL)
    manifest = _manifest("pg_run_save_retrieve")
    save_run(
        conn,
        manifest,
        _result(),
        dataset_id="demo",
        use_llm=False,
        fuzzy_threshold=Decimal("0.90"),
        idempotency_key="pg-key-1",
    )

    stored = db_get_run(conn, "pg_run_save_retrieve")
    assert stored["run_id"] == "pg_run_save_retrieve"
    assert stored["seed"] == 42
    assert stored["total_input_rows"] == 2

    exceptions = get_exceptions(conn, "pg_run_save_retrieve")
    assert len(exceptions) == 1
    assert exceptions[0]["taxonomy_code"] == "BANK_ONLY"
    assert Decimal(exceptions[0]["amount_impact"]) == Decimal("500.00")

    bridge = get_bridge(conn, "pg_run_save_retrieve", "utr1")
    assert bridge["closed"] is True
    assert bridge["rate_variance"]["rule"] == "FEE_VARIANCE"
    assert Decimal(bridge["expected_net"]) == Decimal("976.40")

    utrs = get_bridge_utrs(conn, "pg_run_save_retrieve")
    assert utrs == [
        {
            "settlement_utr": "utr1",
            "closed": True,
            "attribution_rule": None,
            "rate_variance_rule": "FEE_VARIANCE",
        }
    ]


@pytest.mark.skipif(_SKIP, reason=_SKIP_REASON)
def test_find_run_by_idempotency_key_against_real_postgres():
    conn = build_postgres_connection(_DATABASE_URL)
    manifest = _manifest("pg_run_idempotency")
    save_run(
        conn,
        manifest,
        _result(),
        dataset_id="demo",
        use_llm=False,
        fuzzy_threshold=Decimal("0.90"),
        idempotency_key="pg-idempotency-key",
    )
    assert find_run_by_idempotency_key(conn, "pg-idempotency-key") == "pg_run_idempotency"
    assert find_run_by_idempotency_key(conn, "no-such-key") is None


class _FlakyConnection:
    """Same fault-injection wrapper as tests/test_db.py -- duplicated
    rather than imported, matching this file's existing pattern of
    keeping its own fixtures self-contained rather than sharing state
    with the DuckDB test file."""

    def __init__(self, real_conn, fail_on_call: int):
        self._real = real_conn
        self._call_count = 0
        self._fail_on_call = fail_on_call

    def execute(self, sql, params=None):
        self._call_count += 1
        if self._call_count == self._fail_on_call:
            raise RuntimeError(f"simulated crash on execute() call #{self._fail_on_call}")
        return self._real.execute(sql, params)


@pytest.mark.skipif(_SKIP, reason=_SKIP_REASON)
def test_save_run_rolls_back_completely_on_a_mid_write_failure_against_real_postgres():
    """Same regression as tests/test_db.py's DuckDB version, proving the
    BEGIN/COMMIT/ROLLBACK in save_run also works against a real psycopg
    connection in autocommit=True mode, not just DuckDB."""
    conn = build_postgres_connection(_DATABASE_URL)
    flaky = _FlakyConnection(conn, fail_on_call=4)

    try:
        save_run(
            flaky,
            _manifest("pg_run_rollback"),
            _result(),
            dataset_id="demo",
            use_llm=False,
            fuzzy_threshold=Decimal("0.90"),
            idempotency_key="pg-rollback-key",
        )
        raise AssertionError("expected save_run to propagate the simulated failure")
    except RuntimeError as exc:
        assert "simulated crash" in str(exc)

    assert db_get_run(conn, "pg_run_rollback") is None
    assert get_exceptions(conn, "pg_run_rollback") == []
    assert get_bridge_utrs(conn, "pg_run_rollback") == []
