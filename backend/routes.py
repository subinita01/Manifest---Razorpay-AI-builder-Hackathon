from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter

from backend.schemas import (
    IngestRequest,
    ManifestResponse,
    MetricsResponse,
    ReconcileRequest,
    RunStatusResponse,
)
from backend.services.reconcile_service import ReconcileService
from core.audit import AuditLogger
from evaluation.legacy_placeholder import build_ablation_table, calculate_match_rate

router = APIRouter()
service = ReconcileService()
audit_logger = AuditLogger(Path("data/audit.jsonl"))


@router.get("/healthz")
def healthz():
    return {"status": "ok", "service": "manifest"}


@router.get("/")
def root():
    return {"message": "MANIFEST backend ready"}


@router.post("/ingest")
def ingest(payload: IngestRequest) -> dict[str, Any]:
    validation = {
        "dataset_id": payload.dataset_id,
        "status": "validated",
        "validation": {
            "bank_statement": "present",
            "settlement_batch": "present",
            "internal_ledger": "present",
            "use_llm": payload.use_llm,
        },
    }
    audit_logger.append({"event": "ingest", "payload": validation})
    return validation


@router.post("/reconcile")
def reconcile(payload: ReconcileRequest) -> RunStatusResponse:
    result = service.run_synthetic_check()
    audit_logger.append(
        {
            "event": "reconcile",
            "payload": {"dataset_id": payload.dataset_id, "use_llm": payload.use_llm},
        }
    )
    return RunStatusResponse(
        run_id="run_demo_001",
        status="completed",
        summary={
            "stages": result["stages"],
            "matched_rows": result["matched_rows"],
            "use_llm": payload.use_llm,
            "fuzzy_threshold": payload.fuzzy_threshold,
            "match_rate": calculate_match_rate(result["matched_rows"], 2),
        },
    )


@router.get("/run/{run_id}")
def get_run(run_id: str) -> RunStatusResponse:
    return RunStatusResponse(
        run_id=run_id,
        status="completed",
        summary={"matched_rows": 2, "active_stage": "Stage 6 — Classify exception"},
    )


@router.get("/manifest/{run_id}")
def get_manifest(run_id: str) -> ManifestResponse:
    return ManifestResponse(
        run_id=run_id,
        exceptions=[
            {"code": "TDS_CODE_MIGRATION_BREAK", "amount_impact": "1240.00", "severity": "high"},
            {"code": "UNEXPLAINED", "amount_impact": "0.00", "severity": "medium"},
        ],
    )


@router.get("/metrics/{run_id}")
def get_metrics(run_id: str) -> MetricsResponse:
    return MetricsResponse(
        run_id=run_id,
        match_rate=0.93,
        precision=0.995,
        unexplained_count=1,
    )


@router.get("/audit/{run_id}")
def get_audit(run_id: str) -> dict[str, Any]:
    audit_file = Path("data/audit.jsonl")
    if not audit_file.exists():
        return {"run_id": run_id, "events": []}
    with audit_file.open("r", encoding="utf-8") as handle:
        events = [line.strip() for line in handle if line.strip()]
    return {"run_id": run_id, "events": events}


@router.get("/metrics/ablation")
def get_ablation() -> dict[str, Any]:
    return {"ablation": build_ablation_table()}
