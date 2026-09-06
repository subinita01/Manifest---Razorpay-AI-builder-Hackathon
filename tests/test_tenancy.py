"""Cross-tenant isolation tests. Each MANIFEST_API_KEYS label is now a
real authorization boundary (backend/deps.py's get_db_connection.__doc__
covers the plumbing; this file proves the boundary itself actually holds
over real HTTP requests, not just at the db.py unit level).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import backend.db as db_module
from backend.main import app
from backend.routes import limiter


def _client_for(monkeypatch, tmp_path, api_keys: str, key: str) -> TestClient:
    monkeypatch.setattr(db_module, "DEFAULT_DB_PATH", tmp_path / "test.duckdb")
    monkeypatch.setenv("MANIFEST_API_KEYS", api_keys)
    # The Limiter's in-memory storage is a module-level singleton shared
    # by every test in the process -- without resetting it, whether a
    # test in this file sees a 429 depends on how many /reconcile calls
    # earlier tests happened to make (see tests/conftest.py's client
    # fixture, which does the same reset for the same reason).
    limiter.reset()
    return TestClient(app, headers={"X-API-Key": key})


def _two_tenants(monkeypatch, tmp_path):
    api_keys = "tenant-a:key-a,tenant-b:key-b"
    client_a = _client_for(monkeypatch, tmp_path, api_keys, "key-a")
    client_b = TestClient(app, headers={"X-API-Key": "key-b"})
    return client_a, client_b


def test_identical_reconcile_request_from_two_tenants_gets_independent_runs(monkeypatch, tmp_path):
    """No explicit Idempotency-Key -- relies entirely on
    compute_idempotency_key baking tenant_id into the derived hash."""
    client_a, client_b = _two_tenants(monkeypatch, tmp_path)

    response_a = client_a.post("/reconcile", json={"dataset_id": "demo", "use_llm": False})
    response_b = client_b.post("/reconcile", json={"dataset_id": "demo", "use_llm": False})
    assert response_a.status_code == 200
    assert response_b.status_code == 200
    assert response_a.json()["run_id"] != response_b.json()["run_id"]

    # Same underlying dataset, so the same core numbers -- isolation is
    # about ownership, not about computing a different answer.
    assert response_a.json()["summary"] == response_b.json()["summary"]


def test_tenant_cannot_read_another_tenants_run(monkeypatch, tmp_path):
    client_a, client_b = _two_tenants(monkeypatch, tmp_path)
    run_id = client_a.post("/reconcile", json={"dataset_id": "demo"}).json()["run_id"]

    own = client_a.get(f"/run/{run_id}")
    other = client_b.get(f"/run/{run_id}")
    assert own.status_code == 200
    assert other.status_code == 404


def test_tenant_cannot_read_another_tenants_manifest(monkeypatch, tmp_path):
    client_a, client_b = _two_tenants(monkeypatch, tmp_path)
    run_id = client_a.post("/reconcile", json={"dataset_id": "demo"}).json()["run_id"]

    own = client_a.get(f"/manifest/{run_id}")
    other = client_b.get(f"/manifest/{run_id}")
    assert own.status_code == 200
    assert len(own.json()["exceptions"]) > 0
    assert other.status_code == 404


def test_tenant_cannot_read_another_tenants_metrics(monkeypatch, tmp_path):
    client_a, client_b = _two_tenants(monkeypatch, tmp_path)
    run_id = client_a.post("/reconcile", json={"dataset_id": "demo"}).json()["run_id"]

    own = client_a.get(f"/metrics/{run_id}")
    other = client_b.get(f"/metrics/{run_id}")
    assert own.status_code == 200
    assert other.status_code == 404


def test_tenant_cannot_read_another_tenants_bridge(monkeypatch, tmp_path):
    client_a, client_b = _two_tenants(monkeypatch, tmp_path)
    run_id = client_a.post("/reconcile", json={"dataset_id": "demo"}).json()["run_id"]

    # get_bridge_utrs takes no tenant_id (it relies on the caller having
    # already proven run_id ownership) -- fine to call directly here just
    # to find a real settlement_utr to test /bridge against.
    from app.bridge_presets import pick_clean_default

    conn = db_module.get_connection()
    utrs = db_module.get_bridge_utrs(conn, run_id)
    settlement_utr = pick_clean_default(utrs)
    assert settlement_utr is not None, "demo dataset should have at least one closed bridge"

    own = client_a.get(f"/bridge/{run_id}/{settlement_utr}")
    other = client_b.get(f"/bridge/{run_id}/{settlement_utr}")
    assert own.status_code == 200
    assert other.status_code == 404


def test_tenant_cannot_read_another_tenants_audit(monkeypatch, tmp_path):
    client_a, client_b = _two_tenants(monkeypatch, tmp_path)
    run_id = client_a.post("/reconcile", json={"dataset_id": "demo"}).json()["run_id"]

    own = client_a.get(f"/audit/{run_id}")
    other = client_b.get(f"/audit/{run_id}")
    assert own.status_code == 200
    assert other.status_code == 404


def test_audit_for_a_run_id_that_never_existed_is_also_404(monkeypatch, tmp_path):
    """A real behavior fix bundled with tenancy: /audit used to return 200
    with an empty event list for ANY run_id, including ones that never
    existed -- the only endpoint that didn't 404 on an unknown run_id.
    Ownership now has to be checked first regardless of tenant, which
    closes that inconsistency too."""
    client_a, _ = _two_tenants(monkeypatch, tmp_path)
    response = client_a.get("/audit/00000000000000000000000000000000")
    assert response.status_code == 404


def test_uploaded_dataset_is_isolated_per_tenant(monkeypatch, tmp_path):
    """Tenant B can't reconcile against a dataset tenant A uploaded, even
    knowing its exact dataset_id -- it resolves under a different
    tenant-scoped directory (backend/security.py:dataset_dir) that
    doesn't exist from tenant B's side."""
    from pathlib import Path

    client_a, client_b = _two_tenants(monkeypatch, tmp_path)
    demo_dir = Path(__file__).resolve().parent.parent / "data" / "demo"
    files = {
        "bank_statement": ("bank_statement.csv", (demo_dir / "bank_statement.csv").read_bytes()),
        "settlement_batch": (
            "settlement_batch.csv",
            (demo_dir / "settlement_batch.csv").read_bytes(),
        ),
        "internal_ledger": (
            "internal_ledger.csv",
            (demo_dir / "internal_ledger.csv").read_bytes(),
        ),
    }
    ingest_response = client_a.post("/ingest", files=files)
    assert ingest_response.status_code == 200
    dataset_id = ingest_response.json()["dataset_id"]

    reconcile_as_owner = client_a.post("/reconcile", json={"dataset_id": dataset_id})
    reconcile_as_other = client_b.post("/reconcile", json={"dataset_id": dataset_id})
    assert reconcile_as_owner.status_code == 200
    assert reconcile_as_other.status_code == 404
