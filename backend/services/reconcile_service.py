"""Runs the real pipeline against a resolved dataset and persists the result.

No fabricated numbers: every field returned here comes from an actual
core.pipeline.run_pipeline call over the dataset's own CSVs.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal
from pathlib import Path

import duckdb

from backend import db
from backend.security import UnsafePath, dataset_dir, validate_dataset_id
from core.ingest import load_bank_csv, load_ledger_csv, load_settlement_csv
from core.pipeline import run_pipeline
from core.run_manifest import build_run_manifest

ROOT = Path(__file__).resolve().parent.parent.parent
DEMO_DIR = ROOT / "data" / "demo"


class DatasetNotFound(FileNotFoundError):
    pass


def resolve_dataset_dir(dataset_id: str) -> Path:
    dataset_id = validate_dataset_id(dataset_id)
    directory = DEMO_DIR if dataset_id == "demo" else dataset_dir(dataset_id)
    if not directory.exists():
        raise DatasetNotFound(dataset_id)
    return directory


def compute_idempotency_key(
    dataset_id: str,
    use_llm: bool,
    fuzzy_threshold: float,
    explicit_key: str | None = None,
) -> str:
    """Uses the client-supplied Idempotency-Key header when present;
    otherwise derives one from the dataset + params so identical requests
    without an explicit header still hit the cache."""
    if explicit_key:
        return explicit_key
    payload = json.dumps(
        {"dataset_id": dataset_id, "use_llm": use_llm, "fuzzy_threshold": fuzzy_threshold},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def reconcile(
    conn: duckdb.DuckDBPyConnection,
    dataset_id: str,
    use_llm: bool = False,
    fuzzy_threshold: float = 0.90,
    idempotency_key: str | None = None,
) -> str:
    """Returns a run_id: either freshly computed, or the cached run for an
    identical (dataset, params) combination."""
    key = compute_idempotency_key(dataset_id, use_llm, fuzzy_threshold, idempotency_key)
    existing = db.find_run_by_idempotency_key(conn, key)
    if existing is not None:
        return existing

    directory = resolve_dataset_dir(dataset_id)
    bank_rows = load_bank_csv(directory / "bank_statement.csv")
    settlement_rows = load_settlement_csv(directory / "settlement_batch.csv")
    ledger_rows = load_ledger_csv(directory / "internal_ledger.csv")

    result = run_pipeline(
        bank_rows,
        settlement_rows,
        ledger_rows,
        fuzzy_auto_match_threshold=fuzzy_threshold,
    )

    run_id = uuid.uuid4().hex
    seed = 42 if dataset_id == "demo" else 0
    manifest = build_run_manifest(run_id, seed=seed)

    db.save_run(
        conn,
        manifest,
        result,
        dataset_id=dataset_id,
        use_llm=use_llm,
        fuzzy_threshold=Decimal(str(fuzzy_threshold)),
        idempotency_key=key,
    )
    return run_id


__all__ = [
    "DatasetNotFound",
    "UnsafePath",
    "compute_idempotency_key",
    "reconcile",
    "resolve_dataset_dir",
]
