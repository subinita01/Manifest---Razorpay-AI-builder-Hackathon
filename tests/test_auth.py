from fastapi.testclient import TestClient

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
