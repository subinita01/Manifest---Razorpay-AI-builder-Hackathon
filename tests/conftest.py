import pytest
from fastapi.testclient import TestClient

import backend.db as db_module
from backend.main import app
from backend.routes import limiter


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DEFAULT_DB_PATH", tmp_path / "test.duckdb")
    # The Limiter's in-memory storage is a module-level singleton shared by
    # every test in the process; without resetting it, whether a test sees
    # a 429 depends on how many /reconcile calls earlier tests happened to
    # make, which is exactly the kind of order-dependent flakiness that
    # shouldn't exist.
    limiter.reset()
    return TestClient(app)
