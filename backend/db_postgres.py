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
"""

from __future__ import annotations

from typing import Any

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
    exception_row_count INTEGER
);

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
    def __init__(self, dsn: str):
        import psycopg

        self._conn = psycopg.connect(dsn, autocommit=True)

    def execute(self, sql: str, params: list[Any] | None = None) -> Any:
        translated, params = translate_placeholders(sql, params)
        cursor = self._conn.cursor()
        cursor.execute(translated, params)
        return cursor


def build_postgres_connection(database_url: str) -> PostgresConnection:
    conn = PostgresConnection(database_url)
    conn.execute(PG_SCHEMA)
    return conn
