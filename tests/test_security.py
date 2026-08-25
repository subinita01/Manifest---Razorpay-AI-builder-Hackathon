"""Attacks this project's threat model claims to defend against, each one
actually attempted rather than asserted. See SECURITY.md for the mapping
from threat -> control -> test.
"""

from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient

from backend.export import exceptions_to_csv
from backend.security import UPLOAD_DIR

DEMO_DIR = Path(__file__).resolve().parent.parent / "data" / "demo"


def _demo_files():
    return {
        "bank_statement": (
            "../../etc/passwd",
            (DEMO_DIR / "bank_statement.csv").read_bytes(),
            "text/csv",
        ),
        "settlement_batch": (
            "settlement_batch.csv",
            (DEMO_DIR / "settlement_batch.csv").read_bytes(),
            "text/csv",
        ),
        "internal_ledger": (
            "internal_ledger.csv",
            (DEMO_DIR / "internal_ledger.csv").read_bytes(),
            "text/csv",
        ),
    }


def test_t3_path_traversal_via_malicious_upload_filename(client: TestClient):
    """T3: a client-supplied filename like '../../etc/passwd' must never
    become part of the filesystem path the server writes to."""
    response = client.post("/ingest", files=_demo_files())
    assert response.status_code == 200
    dataset_id = response.json()["dataset_id"]

    # The file must have landed inside uploads/<dataset_id>/, under the
    # server-chosen name, never anywhere resolving outside UPLOAD_DIR.
    expected_path = UPLOAD_DIR / dataset_id / "bank_statement.csv"
    assert expected_path.exists()
    assert UPLOAD_DIR.resolve() in expected_path.resolve().parents

    # And definitely not written to an actual /etc/passwd anywhere.
    assert not Path("/etc/passwd_MANIFEST_TEST_MARKER").exists()


def test_t4_oversized_upload_is_rejected(client: TestClient):
    """T4: an upload over the 10MB ceiling is rejected, not silently
    accepted and buffered into memory."""
    oversized = io.BytesIO(b"x" * (11 * 1024 * 1024))
    files = {
        "bank_statement": ("bank_statement.csv", oversized, "text/csv"),
        "settlement_batch": (
            "settlement_batch.csv",
            io.BytesIO((DEMO_DIR / "settlement_batch.csv").read_bytes()),
            "text/csv",
        ),
        "internal_ledger": (
            "internal_ledger.csv",
            io.BytesIO((DEMO_DIR / "internal_ledger.csv").read_bytes()),
            "text/csv",
        ),
    }
    response = client.post("/ingest", files=files)
    assert response.status_code == 413


def test_csv_formula_injection_payload_is_neutralised_on_export():
    """A CSV cell containing a formula-injection payload must never reach
    an exported file unescaped -- Excel treats a leading =/+/-/@ as the
    start of a formula."""
    payload = "=cmd|'/c calc'!A1"
    exceptions = [
        {
            "exception_id": "exc1",
            "taxonomy_code": "BANK_ONLY",
            "severity": "WARN",
            "row_ids": ["3"],
            "amount_impact": "500.00",
            "detail": {"narration": payload},
        }
    ]
    csv_text = exceptions_to_csv(exceptions)

    import csv

    rows = list(csv.reader(io.StringIO(csv_text)))
    for field in rows[1]:
        assert not field.startswith(("=", "+", "-", "@")), field


def test_t8_internal_error_never_leaks_a_traceback(client: TestClient, monkeypatch):
    """T8 disclosure: an unhandled internal error returns a generic error
    body with a correlation_id, never a traceback or exception message."""
    import backend.routes as routes_module

    def _boom(*args, **kwargs):
        raise RuntimeError("some sensitive internal detail: db password is hunter2")

    monkeypatch.setattr(routes_module, "reconcile", _boom)

    response = client.post("/reconcile", json={"dataset_id": "demo"})
    assert response.status_code == 500
    body = response.json()
    assert set(body.keys()) == {"error", "correlation_id"}
    body_text = response.text
    assert "hunter2" not in body_text
    assert "Traceback" not in body_text
    assert "RuntimeError" not in body_text


def test_rate_limiting_blocks_the_11th_rapid_reconcile_request(client: TestClient):
    """10/minute on /reconcile: the 11th rapid request in the same window
    must be rejected with 429."""
    statuses = []
    for i in range(11):
        response = client.post(
            "/reconcile", json={"dataset_id": "demo", "fuzzy_threshold": 0.5 + i * 0.001}
        )
        statuses.append(response.status_code)
    assert statuses[:10].count(429) == 0
    assert 429 in statuses, statuses
