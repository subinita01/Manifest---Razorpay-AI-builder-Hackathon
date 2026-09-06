"""Tests for backend/deps.py's get_db_connection FastAPI dependency,
driven directly as a generator (next()/throw()) -- the same before/after
mechanics FastAPI itself uses internally to run a yield-dependency,
without needing a full app or TestClient.
"""

from __future__ import annotations

import os

import pytest
from fastapi import HTTPException

import backend.db as db_module
from backend.deps import get_db_connection


def test_yields_a_working_duckdb_connection_when_no_database_url(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(db_module, "DEFAULT_DB_PATH", tmp_path / "test.duckdb")

    gen = get_db_connection()
    conn = next(gen)
    assert conn.execute("SELECT 1").fetchone() == (1,)
    with pytest.raises(StopIteration):
        next(gen)  # the post-yield half runs and the generator ends cleanly


def test_raises_503_when_duckdb_connection_acquisition_fails(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    def _broken(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(db_module, "get_connection", _broken)

    gen = get_db_connection()
    with pytest.raises(HTTPException) as exc_info:
        next(gen)
    assert exc_info.value.status_code == 503


def test_endpoint_body_exception_propagates_unchanged_not_as_503(monkeypatch, tmp_path):
    """Regression test for a real bug caught while writing this
    dependency: wrapping the whole function (acquisition *and* the
    yield) in one try/except also catches whatever the endpoint body
    raises, misreporting an unrelated application error -- a genuine
    bug, a 404, whatever -- as "database unavailable". Only the
    acquisition step may translate to a 503."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(db_module, "DEFAULT_DB_PATH", tmp_path / "test.duckdb")

    gen = get_db_connection()
    next(gen)  # acquire successfully
    with pytest.raises(ValueError, match="unrelated bug"):
        gen.throw(ValueError("unrelated bug"))


# --- Integration tests against a real, pooled Postgres ---------------------


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


@pytest.mark.skipif(_SKIP, reason=_SKIP_REASON)
def test_yields_a_working_pooled_postgres_connection():
    gen = get_db_connection()
    conn = next(gen)
    assert conn.execute("SELECT 1").fetchone() == (1,)
    with pytest.raises(StopIteration):
        next(gen)


@pytest.mark.skipif(_SKIP, reason=_SKIP_REASON)
def test_pooled_connection_endpoint_body_exception_propagates_unchanged():
    """Same regression as the DuckDB version above, but for the pooled
    branch specifically -- it has its own, more complex exception-
    forwarding logic (manual __enter__/__exit__ instead of a plain
    try/except around the yield), so it needs its own proof."""
    gen = get_db_connection()
    next(gen)
    with pytest.raises(ValueError, match="unrelated bug"):
        gen.throw(ValueError("unrelated bug"))


@pytest.mark.skipif(_SKIP, reason=_SKIP_REASON)
def test_pooled_connection_is_reused_not_reopened_per_request():
    from backend.db_postgres import _get_pool

    pool_before = _get_pool(_DATABASE_URL)
    stats_before = pool_before.get_stats()["connections_num"]

    for _ in range(3):
        gen = get_db_connection()
        conn = next(gen)
        conn.execute("SELECT 1").fetchone()
        with pytest.raises(StopIteration):
            next(gen)

    pool_after = _get_pool(_DATABASE_URL)
    assert pool_after is pool_before
    assert pool_after.get_stats()["connections_num"] == stats_before
