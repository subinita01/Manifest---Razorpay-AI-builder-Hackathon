"""Postgres backend for backend/db.py's query functions -- used only when
DATABASE_URL is set. psycopg is imported here and nowhere else, the same
deferred-import convention llm/adapter.py uses for optional provider SDKs,
so nothing breaks for anyone who never sets DATABASE_URL and never installs
psycopg.

Every query function in backend/db.py (save_run, get_run, get_exceptions,
get_bridge, get_bridge_utrs, find_run_by_idempotency_key) is written as
conn.execute(sql, params).fetchone()/.fetchall() and stays completely
unchanged for Postgres -- it only relies on .execute() returning something
with .fetchone()/.fetchall(), never on which concrete type that is.
PostgresConnection.execute() returns a real psycopg cursor, which has both,
so it drops in with zero changes to any query.

The one real difference from DuckDB's SQL: DuckDB accepts `?` placeholders,
psycopg needs `%s`. PostgresConnection.execute() translates via a plain
string replace, which is only safe because no query in backend/db.py ever
contains a literal `?` inside a string value -- true today, and guarded
(not proven) by the placeholder/param-count assertion below, which catches
most accidental mismatches without being a complete proof.

Two ways to get a PostgresConnection: build_postgres_connection() opens
one fresh connection per call (used by tests and by backend/db.py's
non-pooled fallback), and pooled_connection() checks one out of a
process-wide psycopg_pool.ConnectionPool instead -- see backend/deps.py,
which is what backend/routes.py actually uses.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

    from psycopg_pool import ConnectionPool

# Same four tables as backend/db.py's SCHEMA, Postgres-flavored. The only
# type that actually differs is DOUBLE -> DOUBLE PRECISION (matches.confidence);
# DECIMAL(p,s), BOOLEAN, TEXT, INTEGER, TIMESTAMP, and CREATE INDEX IF NOT
# EXISTS are valid, identical Postgres syntax.
PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    dataset_id TEXT,
    seed INTEGER,
    git_sha TEXT,
    config_hash TEXT,
    model_string TEXT,
    library_versions TEXT,
    created_at TIMESTAMP,
    use_llm BOOLEAN,
    fuzzy_threshold DECIMAL(5,4),
    idempotency_key TEXT,
    total_input_rows INTEGER,
    matched_row_count INTEGER,
    needs_review_row_count INTEGER,
    exception_row_count INTEGER,
    tenant_id TEXT
);

-- CREATE TABLE IF NOT EXISTS is a no-op against a runs table that already
-- existed before tenant_id was added, so an explicit ALTER is what
-- actually lands the column on a pre-existing Postgres database.
ALTER TABLE runs ADD COLUMN IF NOT EXISTS tenant_id TEXT;

CREATE TABLE IF NOT EXISTS matches (
    run_id TEXT,
    match_id TEXT,
    bucket TEXT,
    stage_name TEXT,
    bank_row_id TEXT,
    settlement_row_id TEXT,
    ledger_row_id TEXT,
    confidence DOUBLE PRECISION,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS exceptions (
    run_id TEXT,
    exception_id TEXT,
    taxonomy_code TEXT,
    severity TEXT,
    row_ids TEXT,
    amount_impact DECIMAL(18,4),
    detail TEXT
);

CREATE TABLE IF NOT EXISTS bridges (
    run_id TEXT,
    settlement_utr TEXT,
    steps TEXT,
    expected_net DECIMAL(18,4),
    bank_credit DECIMAL(18,4),
    residual DECIMAL(18,4),
    closed BOOLEAN,
    attribution TEXT,
    rate_variance TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_idempotency ON runs(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_runs_tenant ON runs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_matches_run ON matches(run_id);
CREATE INDEX IF NOT EXISTS idx_exceptions_run ON exceptions(run_id);
CREATE INDEX IF NOT EXISTS idx_bridges_run_utr ON bridges(run_id, settlement_utr);
"""


class PlaceholderMismatch(ValueError):
    """Raised when a query's `?` count doesn't match the params list --
    almost always a sign the `?` -> `%s` translation would silently
    corrupt the query rather than a real usage error."""


def translate_placeholders(sql: str, params: list[Any] | None) -> tuple[str, list[Any]]:
    """Pure, connection-free so it's unit-testable without a real Postgres:
    translates '?' -> '%s' and asserts the count matches len(params)."""
    params = params or []
    placeholder_count = sql.count("?")
    if placeholder_count != len(params):
        raise PlaceholderMismatch(
            f"query has {placeholder_count} '?' placeholders but {len(params)} "
            "params were given -- refusing to translate, since a mismatch here "
            "means the '?' -> '%s' rewrite would silently corrupt the query"
        )
    return sql.replace("?", "%s"), params


class PostgresConnection:
    """Wraps an already-open psycopg connection -- either a fresh one
    (build_postgres_connection) or one checked out of a pool
    (pooled_connection). The wrapper itself doesn't care which; both give
    it a real psycopg connection with autocommit=True already set."""

    def __init__(self, psycopg_conn: Any):
        self._conn = psycopg_conn

    def execute(self, sql: str, params: list[Any] | None = None) -> Any:
        translated, params = translate_placeholders(sql, params)
        cursor = self._conn.cursor()
        cursor.execute(translated, params)
        return cursor


def build_postgres_connection(database_url: str) -> PostgresConnection:
    """One fresh connection, not pooled -- used by tests and by
    backend/db.py's get_connection() when nothing has requested a pool."""
    import psycopg

    conn = PostgresConnection(psycopg.connect(database_url, autocommit=True))
    conn.execute(PG_SCHEMA)
    return conn


_POOLS: dict[str, ConnectionPool] = {}


def _get_pool(database_url: str) -> ConnectionPool:
    # One pool per distinct database_url, created once per process and
    # reused for the process's lifetime -- not per-request, which would
    # defeat the point of pooling.
    pool = _POOLS.get(database_url)
    if pool is not None:
        return pool

    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(
        database_url,
        min_size=1,
        max_size=10,
        kwargs={"autocommit": True},
        open=True,  # explicit: psycopg_pool 3.3 warns that the implicit default will flip to False
    )
    pool.wait()  # fail fast on a bad DATABASE_URL rather than on the first request
    with pool.connection() as conn:
        PostgresConnection(conn).execute(PG_SCHEMA)
    _POOLS[database_url] = pool
    return pool


@contextmanager
def pooled_connection(database_url: str) -> Iterator[PostgresConnection]:
    """Checks a connection out of the process-wide pool for database_url,
    wraps it, and returns it to the pool when the caller's `with` block
    exits -- normally or via an exception. psycopg_pool resets a
    connection on return (rolling back any open transaction), so a
    caller that raised mid-transaction (e.g. backend/db.py's save_run on
    a ROLLBACK path) can't leave the next checkout in a broken state."""
    pool = _get_pool(database_url)
    with pool.connection() as conn:
        yield PostgresConnection(conn)
