import pytest
from fastapi.testclient import TestClient

import backend.audit_log as audit_log_module
import backend.db as db_module
from backend.main import app
from backend.routes import limiter


@pytest.fixture(autouse=True)
def _isolated_audit_log(tmp_path, monkeypatch):
    # Every test that runs reconcile_service.reconcile() (directly, or via
    # the /reconcile or /ingest endpoints) appends to the audit log --
    # without this, every test run silently grows the real
    # data/audit.jsonl by dozens of lines (one per exception decision plus
    # a summary record), which is exactly what happened before this
    # fixture existed: a 1000-line, 495KB file accumulated from test runs
    # alone. autouse so no current or future test can reintroduce it.
    monkeypatch.setattr(audit_log_module, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")


TEST_API_KEY = "test-key"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DEFAULT_DB_PATH", tmp_path / "test.duckdb")
    monkeypatch.setenv("MANIFEST_API_KEYS", TEST_API_KEY)
    # The Limiter's in-memory storage is a module-level singleton shared by
    # every test in the process; without resetting it, whether a test sees
    # a 429 depends on how many /reconcile calls earlier tests happened to
    # make, which is exactly the kind of order-dependent flakiness that
    # shouldn't exist.
    limiter.reset()
    # TestClient (httpx) merges these into every request, so every existing
    # test written before backend/auth.py existed keeps passing unmodified.
    return TestClient(app, headers={"X-API-Key": TEST_API_KEY})
