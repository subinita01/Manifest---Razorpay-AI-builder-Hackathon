"""DuckDB persistence for pipeline runs.

Money columns are DECIMAL(18,4), never REAL -- the same invariant
CLAUDE.md holds core/ to. This module is backend-only (it imports
core.pipeline/core.models for typing, but core/ never imports this file).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from core.models import RunManifest
from core.pipeline import RunResult

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "manifest.duckdb"

SCHEMA = """
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
    confidence DOUBLE,
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


def get_connection(db_path: Path | None = None) -> duckdb.DuckDBPyConnection:
    # Resolves DEFAULT_DB_PATH at call time, not def time, so tests can
    # monkeypatch backend.db.DEFAULT_DB_PATH and have every no-arg caller
    # (routes.py) pick up the patched value.
    path = db_path if db_path is not None else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(path))
    conn.execute(SCHEMA)
    return conn


def find_run_by_idempotency_key(
    conn: duckdb.DuckDBPyConnection, idempotency_key: str
) -> str | None:
    row = conn.execute(
        "SELECT run_id FROM runs WHERE idempotency_key = ? LIMIT 1", [idempotency_key]
    ).fetchone()
    return row[0] if row else None


def save_run(
    conn: duckdb.DuckDBPyConnection,
    manifest: RunManifest,
    result: RunResult,
    dataset_id: str,
    use_llm: bool,
    fuzzy_threshold: Decimal,
    idempotency_key: str,
) -> None:
    conn.execute(
        "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            manifest.run_id,
            dataset_id,
            manifest.seed,
            manifest.git_sha,
            manifest.config_hash,
            manifest.model_string,
            json.dumps(manifest.library_versions),
            manifest.created_at,
            use_llm,
            fuzzy_threshold,
            idempotency_key,
            result.total_input_rows,
            result.matched_row_count,
            result.needs_review_row_count,
            result.exception_row_count,
        ],
    )

    for bucket, matches in (("matched", result.matched), ("needs_review", result.needs_review)):
        for m in matches:
            conn.execute(
                "INSERT INTO matches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    manifest.run_id,
                    m.match_id,
                    bucket,
                    m.stage_name,
                    m.bank_row_id,
                    m.settlement_row_id,
                    m.ledger_row_id,
                    m.confidence,
                    json.dumps(m.detail, default=str),
                ],
            )

    for e in result.exceptions:
        conn.execute(
            "INSERT INTO exceptions VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                manifest.run_id,
                e.exception_id,
                e.taxonomy_code,
                e.severity,
                json.dumps(e.row_ids),
                e.amount_impact,
                json.dumps(e.detail, default=str),
            ],
        )

    for utr, bridge in result.bridges.items():
        steps = [
            {
                "label": s.label,
                "amount": str(s.amount),
                "running_total": str(s.running_total),
                "constituent_row_ids": s.constituent_row_ids,
            }
            for s in bridge.steps
        ]
        attribution = (
            {"rule": bridge.attribution.rule, "detail": bridge.attribution.detail}
            if bridge.attribution
            else None
        )
        rate_variance = (
            {"rule": bridge.rate_variance.rule, "detail": bridge.rate_variance.detail}
            if bridge.rate_variance
            else None
        )
        conn.execute(
            "INSERT INTO bridges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                manifest.run_id,
                utr,
                json.dumps(steps),
                bridge.expected_net,
                bridge.bank_credit,
                bridge.residual,
                bridge.closed,
                json.dumps(attribution),
                json.dumps(rate_variance),
            ],
        )


def get_run(conn: duckdb.DuckDBPyConnection, run_id: str) -> dict[str, Any] | None:
    columns = [
        "run_id",
        "dataset_id",
        "seed",
        "git_sha",
        "config_hash",
        "model_string",
        "library_versions",
        "created_at",
        "use_llm",
        "fuzzy_threshold",
        "idempotency_key",
        "total_input_rows",
        "matched_row_count",
        "needs_review_row_count",
        "exception_row_count",
    ]
    row = conn.execute(
        f"SELECT {', '.join(columns)} FROM runs WHERE run_id = ?", [run_id]
    ).fetchone()
    if row is None:
        return None
    record = dict(zip(columns, row))
    record["library_versions"] = json.loads(record["library_versions"])
    return record


def get_exceptions(conn: duckdb.DuckDBPyConnection, run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT exception_id, taxonomy_code, severity, row_ids, amount_impact, detail "
        "FROM exceptions WHERE run_id = ?",
        [run_id],
    ).fetchall()
    return [
        {
            "exception_id": r[0],
            "taxonomy_code": r[1],
            "severity": r[2],
            "row_ids": json.loads(r[3]),
            "amount_impact": str(r[4]),
            "detail": json.loads(r[5]),
        }
        for r in rows
    ]


def get_bridge_utrs(conn: duckdb.DuckDBPyConnection, run_id: str) -> list[dict[str, Any]]:
    """Every bridge computed for a run, for populating a settlement-batch
    picker without pulling each bridge's full step/detail payload."""
    rows = conn.execute(
        "SELECT settlement_utr, closed, attribution, rate_variance FROM bridges "
        "WHERE run_id = ? ORDER BY settlement_utr",
        [run_id],
    ).fetchall()

    def _rule(raw: str | None) -> str | None:
        parsed = json.loads(raw) if raw else None
        return parsed["rule"] if parsed else None

    return [
        {
            "settlement_utr": r[0],
            "closed": r[1],
            "attribution_rule": _rule(r[2]),
            "rate_variance_rule": _rule(r[3]),
        }
        for r in rows
    ]


def get_bridge(
    conn: duckdb.DuckDBPyConnection, run_id: str, settlement_utr: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT steps, expected_net, bank_credit, residual, closed, attribution, rate_variance "
        "FROM bridges WHERE run_id = ? AND settlement_utr = ?",
        [run_id, settlement_utr],
    ).fetchone()
    if row is None:
        return None
    return {
        "settlement_utr": settlement_utr,
        "steps": json.loads(row[0]),
        "expected_net": str(row[1]),
        "bank_credit": str(row[2]),
        "residual": str(row[3]),
        "closed": row[4],
        "attribution": json.loads(row[5]) if row[5] else None,
        "rate_variance": json.loads(row[6]) if row[6] else None,
    }
