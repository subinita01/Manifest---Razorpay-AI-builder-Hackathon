import json

from fastapi import HTTPException
from fastapi.testclient import TestClient

import backend.audit_log as audit_log_module
import backend.db as db_module
from backend.auth import require_api_key
from backend.main import app
from tests.conftest import TEST_API_KEY


def test_healthz_requires_no_api_key(client: TestClient):
    # The client fixture always sets X-API-Key, so build a bare client here
    # to prove /healthz genuinely doesn't need one -- a load balancer probe
    # never sends one.
    bare_client = TestClient(app)
    response = bare_client.get("/healthz")
    assert response.status_code == 200


def test_protected_endpoint_rejects_missing_api_key(monkeypatch, tmp_path):
    import backend.db as db_module

    monkeypatch.setattr(db_module, "DEFAULT_DB_PATH", tmp_path / "test.duckdb")
    monkeypatch.setenv("MANIFEST_API_KEYS", TEST_API_KEY)
    bare_client = TestClient(app)
    response = bare_client.post("/reconcile", json={"dataset_id": "demo"})
    assert response.status_code == 401


def test_protected_endpoint_rejects_wrong_api_key(monkeypatch, tmp_path):
    import backend.db as db_module

    monkeypatch.setattr(db_module, "DEFAULT_DB_PATH", tmp_path / "test.duckdb")
    monkeypatch.setenv("MANIFEST_API_KEYS", TEST_API_KEY)
    wrong_client = TestClient(app, headers={"X-API-Key": "not-the-right-key"})
    response = wrong_client.post("/reconcile", json={"dataset_id": "demo"})
    assert response.status_code == 401


def test_protected_endpoint_accepts_correct_api_key(client: TestClient):
    response = client.post("/reconcile", json={"dataset_id": "demo", "use_llm": False})
    assert response.status_code == 200


def test_no_configured_keys_denies_every_protected_request(monkeypatch, tmp_path):
    """Fail-closed, not fail-open: an unset MANIFEST_API_KEYS must deny
    every protected request rather than silently allowing everything
    through because nobody configured a key."""
    import backend.db as db_module

    monkeypatch.setattr(db_module, "DEFAULT_DB_PATH", tmp_path / "test.duckdb")
    monkeypatch.delenv("MANIFEST_API_KEYS", raising=False)
    no_key_configured_client = TestClient(app, headers={"X-API-Key": "anything"})
    response = no_key_configured_client.post("/reconcile", json={"dataset_id": "demo"})
    assert response.status_code == 401


def test_require_api_key_returns_the_matched_caller_label(monkeypatch):
    monkeypatch.setenv("MANIFEST_API_KEYS", "priya:priya-key,arjun:arjun-key")
    assert require_api_key(x_api_key="priya-key") == "priya"
    assert require_api_key(x_api_key="arjun-key") == "arjun"


def test_require_api_key_uses_a_bare_key_as_its_own_label(monkeypatch):
    monkeypatch.setenv("MANIFEST_API_KEYS", "dev-local-key-change-me")
    assert require_api_key(x_api_key="dev-local-key-change-me") == "dev-local-key-change-me"


def test_require_api_key_still_rejects_an_invalid_key(monkeypatch):
    monkeypatch.setenv("MANIFEST_API_KEYS", "priya:priya-key")
    try:
        require_api_key(x_api_key="not-priyas-key")
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 401


def test_reconcile_endpoint_records_the_caller_label_in_the_audit_log(monkeypatch, tmp_path):
    monkeypatch.setattr(db_module, "DEFAULT_DB_PATH", tmp_path / "test.duckdb")
    monkeypatch.setenv("MANIFEST_API_KEYS", "priya:priya-key")
    priya_client = TestClient(app, headers={"X-API-Key": "priya-key"})

    response = priya_client.post("/reconcile", json={"dataset_id": "demo", "use_llm": False})
    assert response.status_code == 200
    run_id = response.json()["run_id"]

    records = [
        json.loads(line) for line in audit_log_module.AUDIT_LOG_PATH.read_text().splitlines()
    ]
    reconcile_events = [
        r["event"]
        for r in records
        if r["event"].get("event") == "reconcile" and r["event"].get("run_id") == run_id
    ]
    assert len(reconcile_events) == 1
    assert reconcile_events[0]["caller"] == "priya"


def test_ingest_endpoint_records_the_caller_label_in_the_audit_log(monkeypatch, tmp_path):
    from pathlib import Path

    monkeypatch.setattr(db_module, "DEFAULT_DB_PATH", tmp_path / "test.duckdb")
    monkeypatch.setenv("MANIFEST_API_KEYS", "arjun:arjun-key")
    arjun_client = TestClient(app, headers={"X-API-Key": "arjun-key"})

    demo_dir = Path(__file__).resolve().parent.parent / "data" / "demo"
    with (
        open(demo_dir / "bank_statement.csv", "rb") as bank,
        open(demo_dir / "settlement_batch.csv", "rb") as settlement,
        open(demo_dir / "internal_ledger.csv", "rb") as ledger,
    ):
        response = arjun_client.post(
            "/ingest",
            files={
                "bank_statement": ("bank_statement.csv", bank, "text/csv"),
                "settlement_batch": ("settlement_batch.csv", settlement, "text/csv"),
                "internal_ledger": ("internal_ledger.csv", ledger, "text/csv"),
            },
        )
    assert response.status_code == 200
    dataset_id = response.json()["dataset_id"]

    records = [
        json.loads(line) for line in audit_log_module.AUDIT_LOG_PATH.read_text().splitlines()
    ]
    ingest_events = [
        r["event"]
        for r in records
        if r["event"].get("event") == "ingest" and r["event"].get("dataset_id") == dataset_id
    ]
    assert len(ingest_events) == 1
    assert ingest_events[0]["caller"] == "arjun"
