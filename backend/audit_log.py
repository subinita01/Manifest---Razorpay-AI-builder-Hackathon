"""Shared audit log location for the whole backend, so API-level request
events (backend/routes.py) and pipeline-decision-level events
(backend/services/reconcile_service.py) chain into the same file regardless
of entry point -- an HTTP request or the Streamlit UI's direct in-process
call, which never goes through routes.py at all.
"""

from __future__ import annotations

from pathlib import Path

from core.audit import AuditLogger

AUDIT_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "audit.jsonl"


def get_audit_logger() -> AuditLogger:
    # Resolves AUDIT_LOG_PATH at call time, not def time -- same reason as
    # backend.db.get_connection -- so tests can monkeypatch this module's
    # AUDIT_LOG_PATH and every no-arg caller picks up the patched value,
    # instead of every reconcile()/ingest() call in the test suite silently
    # appending to the real data/audit.jsonl.
    return AuditLogger(AUDIT_LOG_PATH)
