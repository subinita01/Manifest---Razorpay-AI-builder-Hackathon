"""Runs the real pipeline against a resolved dataset and persists the result.

No fabricated numbers: every field returned here comes from an actual
core.pipeline.run_pipeline call over the dataset's own CSVs.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from backend import db
from backend.audit_log import get_audit_logger
from backend.security import UnsafePath, dataset_dir, validate_dataset_id
from core.audit import AuditLogger
from core.ingest import load_bank_csv, load_ledger_csv, load_settlement_csv
from core.pipeline import RunResult, run_pipeline
from core.run_manifest import build_run_manifest

ROOT = Path(__file__).resolve().parent.parent.parent
DEMO_DIR = ROOT / "data" / "demo"

# Maps each taxonomy code back to the stage that actually produced it, since
# Exception_ itself doesn't carry a stage field -- taxonomy_code already
# determines origin deterministically (see core/pipeline.py's Stage 2/4/6
# classification calls).
_EXCEPTION_STAGE = {
    "FEE_VARIANCE": "stage2_bridge",
    "GST_ON_MDR_VARIANCE": "stage2_bridge",
    "ROUNDING": "stage2_bridge",
    "UNEXPLAINED": "stage2_bridge",
    "TDS_CODE_MIGRATION_BREAK": "stage4_tds",
    "TDS_RATE_MISMATCH": "stage4_tds",
    "TDS_AMOUNT_MISMATCH": "stage4_tds",
    "AMBIGUOUS_MATCH": "stage1_stage5_match",
    "BANK_ONLY": "stage5_fuzzy",
    "LEDGER_ONLY": "stage3_order",
    "SETTLEMENT_ONLY": "stage3_order",
}


def _sha256(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def record_pipeline_decisions(
    logger: AuditLogger, run_id: str, dataset_id: str, result: RunResult
) -> None:
    """One audit record per exception -- the "why was this flagged" trail
    an auditor actually needs -- plus one summary record for the run as a
    whole. Deliberately NOT one record per matched row: a thousand-row
    clean match would turn the audit log into noise nobody would ever
    read, and the decisions worth an append-only, tamper-evident trail are
    the ones a human will actually be asked to justify."""
    now = datetime.now(UTC).isoformat()
    logger.append(
        {
            "timestamp": now,
            "run_id": run_id,
            "dataset_id": dataset_id,
            "stage": "pipeline",
            "decision": "run_summary",
            "input_ids": [],
            "sha256": _sha256(
                {
                    "matched_row_count": result.matched_row_count,
                    "needs_review_row_count": result.needs_review_row_count,
                    "exception_row_count": result.exception_row_count,
                    "total_input_rows": result.total_input_rows,
                }
            ),
        }
    )
    for exc in result.exceptions:
        logger.append(
            {
                "timestamp": now,
                "run_id": run_id,
                "dataset_id": dataset_id,
                "stage": _EXCEPTION_STAGE.get(exc.taxonomy_code, "stage6_classify"),
                "decision": exc.taxonomy_code,
                "input_ids": exc.row_ids,
                "sha256": _sha256(exc.detail),
            }
        )


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

    model_string = None
    if use_llm:
        # Deferred imports: llm/ is optional weight core.pipeline never
        # carries, and this is the one place backend/ decides whether to
        # pay it. Reading an API key from the environment is fine here --
        # this is backend/, not core/ (CLAUDE.md rule 2 only restricts
        # core/).
        from llm.adapter import build_adapter_from_env
        from llm.enrich import enrich_run_result

        adapter = build_adapter_from_env()
        model_string = adapter.model_string
        bank_narration_by_row_id = {row["row_id"]: row["narration"] for row in bank_rows}
        enrich_run_result(result, adapter, bank_narration_by_row_id)

    run_id = uuid.uuid4().hex
    seed = 42 if dataset_id == "demo" else 0
    manifest = build_run_manifest(run_id, seed=seed, model_string=model_string)

    record_pipeline_decisions(get_audit_logger(), run_id, dataset_id, result)

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
    "record_pipeline_decisions",
    "resolve_dataset_dir",
]
