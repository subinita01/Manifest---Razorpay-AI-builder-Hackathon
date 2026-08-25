"""API routes wired to the real pipeline (core.pipeline.run_pipeline) and
DuckDB persistence (backend.db) -- no placeholder data.

No `from __future__ import annotations` here deliberately: slowapi's
@limiter.limit decorator wraps the endpoint function, and combined with
postponed evaluation FastAPI/Pydantic fail to resolve the wrapped
function's string annotations (e.g. "ReconcileRequest") back to the real
types. Every annotation in this file must stay a real runtime type, not a
string -- `str | None` etc. work natively on Python 3.11 without it.
"""

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Header, HTTPException, Request, UploadFile
from slowapi import Limiter
from slowapi.util import get_remote_address

from backend import db
from backend.schemas import IngestResponse, ManifestResponse, ReconcileRequest, RunStatusResponse
from backend.security import (
    TooManyRows,
    UnsafePath,
    UploadTooLarge,
    dataset_dir,
    enforce_row_limit,
    new_dataset_id,
    stream_upload_to_file,
)
from backend.services.reconcile_service import DatasetNotFound, reconcile, resolve_dataset_dir
from core.audit import AuditLogger

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

AUDIT_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "audit.jsonl"
audit_logger = AuditLogger(AUDIT_LOG_PATH)


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "manifest"}


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    bank_statement: UploadFile = File(...),
    settlement_batch: UploadFile = File(...),
    internal_ledger: UploadFile = File(...),
) -> IngestResponse:
    dataset_id = new_dataset_id()
    target_dir = dataset_dir(dataset_id)

    uploads = {
        "bank_statement": bank_statement,
        "settlement_batch": settlement_batch,
        "internal_ledger": internal_ledger,
    }
    filenames = {
        "bank_statement": "bank_statement.csv",
        "settlement_batch": "settlement_batch.csv",
        "internal_ledger": "internal_ledger.csv",
    }

    validation: dict[str, Any] = {}
    for key, upload in uploads.items():
        # The client's filename is never used for the destination path
        # (T3): the destination is always this fixed, server-chosen name.
        destination = target_dir / filenames[key]
        try:
            size = await stream_upload_to_file(upload, destination)
        except UploadTooLarge as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        try:
            rows = enforce_row_limit(destination)
        except TooManyRows as exc:
            destination.unlink(missing_ok=True)
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        validation[key] = {"size_bytes": size, "rows": rows}

    audit_logger.append({"event": "ingest", "dataset_id": dataset_id, "validation": validation})
    return IngestResponse(dataset_id=dataset_id, status="validated", validation=validation)


@router.post("/reconcile", response_model=RunStatusResponse)
@limiter.limit("10/minute")
def do_reconcile(
    request: Request,  # required by slowapi's limiter to key on the client IP
    payload: ReconcileRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> RunStatusResponse:
    conn = db.get_connection()
    try:
        run_id = reconcile(
            conn,
            dataset_id=payload.dataset_id,
            use_llm=payload.use_llm,
            fuzzy_threshold=payload.fuzzy_threshold,
            idempotency_key=idempotency_key,
        )
    except UnsafePath as exc:
        raise HTTPException(status_code=400, detail="invalid dataset_id") from exc
    except DatasetNotFound as exc:
        raise HTTPException(status_code=404, detail=f"unknown dataset: {exc}") from exc

    stored = db.get_run(conn, run_id)
    audit_logger.append({"event": "reconcile", "run_id": run_id, "dataset_id": payload.dataset_id})
    return RunStatusResponse(
        run_id=run_id,
        status="completed",
        summary={
            "total_input_rows": stored["total_input_rows"],
            "matched_row_count": stored["matched_row_count"],
            "needs_review_row_count": stored["needs_review_row_count"],
            "exception_row_count": stored["exception_row_count"],
        },
    )


@router.get("/run/{run_id}", response_model=RunStatusResponse)
def get_run(run_id: str) -> RunStatusResponse:
    conn = db.get_connection()
    stored = db.get_run(conn, run_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="unknown run_id")
    return RunStatusResponse(
        run_id=run_id,
        status="completed",
        summary={
            "total_input_rows": stored["total_input_rows"],
            "matched_row_count": stored["matched_row_count"],
            "needs_review_row_count": stored["needs_review_row_count"],
            "exception_row_count": stored["exception_row_count"],
        },
    )


@router.get("/bridge/{run_id}/{settlement_id}")
def get_bridge(run_id: str, settlement_id: str) -> dict[str, Any]:
    """settlement_id here is the settlement_utr identifying the batch, since
    a bridge is computed per UTR-group, not per individual settlement row."""
    conn = db.get_connection()
    bridge = db.get_bridge(conn, run_id, settlement_id)
    if bridge is None:
        raise HTTPException(status_code=404, detail="unknown run_id/settlement_id")
    return bridge


@router.get("/manifest/{run_id}", response_model=ManifestResponse)
def get_manifest(run_id: str) -> ManifestResponse:
    conn = db.get_connection()
    if db.get_run(conn, run_id) is None:
        raise HTTPException(status_code=404, detail="unknown run_id")
    exceptions = db.get_exceptions(conn, run_id)
    return ManifestResponse(run_id=run_id, exceptions=exceptions)


@router.get("/metrics/{run_id}")
def get_metrics(run_id: str) -> dict[str, Any]:
    conn = db.get_connection()
    stored = db.get_run(conn, run_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="unknown run_id")

    basic = {
        "run_id": run_id,
        "total_input_rows": stored["total_input_rows"],
        "matched_row_count": stored["matched_row_count"],
        "needs_review_row_count": stored["needs_review_row_count"],
        "exception_row_count": stored["exception_row_count"],
        "auto_match_rate": (
            stored["matched_row_count"] / stored["total_input_rows"]
            if stored["total_input_rows"]
            else 0.0
        ),
        "ground_truth_metrics_available": False,
    }

    if stored["dataset_id"] != "demo":
        # No ground truth for arbitrary uploaded data -- reporting
        # precision/recall against nothing would be exactly the kind of
        # unearned claim this product's evaluation exists to prevent.
        return basic

    from core.ingest import load_bank_csv, load_ledger_csv, load_settlement_csv
    from core.pipeline import run_pipeline
    from evaluation.metrics import evaluate_run

    directory = resolve_dataset_dir("demo")
    bank_rows = load_bank_csv(directory / "bank_statement.csv")
    settlement_rows = load_settlement_csv(directory / "settlement_batch.csv")
    ledger_rows = load_ledger_csv(directory / "internal_ledger.csv")
    ground_truth = json.loads((directory / "ground_truth.json").read_text())

    result = run_pipeline(
        bank_rows,
        settlement_rows,
        ledger_rows,
        fuzzy_auto_match_threshold=float(stored["fuzzy_threshold"]),
    )
    report = evaluate_run(
        result,
        ground_truth,
        len(bank_rows),
        {r["row_id"]: r["credit"] for r in bank_rows},
        {r["settlement_id"]: r["settlement_utr"] for r in settlement_rows},
    )
    basic.update(
        ground_truth_metrics_available=True,
        matcher_precision=report.matcher_precision,
        matcher_recall=report.matcher_recall,
        exception_macro_f1=report.exception_macro_f1,
        false_positive_cost_inr=str(report.false_positive_cost_inr),
        unresolvable_by_design_detection_rate=report.unresolvable_by_design_detection_rate,
    )
    return basic


@router.get("/audit/{run_id}")
def get_audit(run_id: str) -> dict[str, Any]:
    if not AUDIT_LOG_PATH.exists():
        return {"run_id": run_id, "events": [], "chain_valid": True}
    events = []
    with AUDIT_LOG_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("event", {}).get("run_id") == run_id:
                events.append(record)
    return {"run_id": run_id, "events": events, "chain_valid": audit_logger.verify_chain()}
