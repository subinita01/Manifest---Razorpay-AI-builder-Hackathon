from pathlib import Path

from fastapi.testclient import TestClient

DEMO_DIR = Path(__file__).resolve().parent.parent / "data" / "demo"


def test_healthz(client: TestClient):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "manifest"}


def test_reconcile_and_run_lifecycle_against_demo_dataset(client: TestClient):
    response = client.post("/reconcile", json={"dataset_id": "demo", "use_llm": False})
    assert response.status_code == 200
    body = response.json()
    run_id = body["run_id"]
    assert body["status"] == "completed"
    assert body["summary"]["total_input_rows"] > 1000

    run_response = client.get(f"/run/{run_id}")
    assert run_response.status_code == 200
    assert run_response.json()["run_id"] == run_id

    manifest_response = client.get(f"/manifest/{run_id}")
    assert manifest_response.status_code == 200
    exceptions = manifest_response.json()["exceptions"]
    assert len(exceptions) > 0
    assert any(e["taxonomy_code"] == "TDS_CODE_MIGRATION_BREAK" for e in exceptions)

    metrics_response = client.get(f"/metrics/{run_id}")
    assert metrics_response.status_code == 200
    metrics = metrics_response.json()
    assert metrics["ground_truth_metrics_available"] is True
    assert 0.0 < metrics["matcher_precision"] <= 1.0

    audit_response = client.get(f"/audit/{run_id}")
    assert audit_response.status_code == 200
    assert audit_response.json()["chain_valid"] is True


def test_reconcile_is_idempotent_across_http_requests(client: TestClient):
    first = client.post("/reconcile", json={"dataset_id": "demo"})
    second = client.post("/reconcile", json={"dataset_id": "demo"})
    assert first.json()["run_id"] == second.json()["run_id"]


def test_reconcile_unknown_dataset_returns_404(client: TestClient):
    response = client.post("/reconcile", json={"dataset_id": "00000000000000000000000000000000"})
    assert response.status_code == 404


def test_run_unknown_id_returns_404(client: TestClient):
    assert client.get("/run/does-not-exist").status_code == 404


def test_bridge_for_a_matched_settlement(client: TestClient):
    reconcile_response = client.post("/reconcile", json={"dataset_id": "demo"})
    run_id = reconcile_response.json()["run_id"]

    manifest = client.get(f"/manifest/{run_id}").json()
    fee_variance = next(e for e in manifest["exceptions"] if e["taxonomy_code"] == "FEE_VARIANCE")
    settlement_utr = fee_variance["detail"]["settlement_utr"]

    bridge_response = client.get(f"/bridge/{run_id}/{settlement_utr}")
    assert bridge_response.status_code == 200
    bridge = bridge_response.json()
    assert bridge["closed"] is True
    assert bridge["rate_variance"]["rule"] == "FEE_VARIANCE"


def test_ingest_accepts_the_committed_demo_csvs(client: TestClient):
    files = {
        "bank_statement": ("evil.csv", (DEMO_DIR / "bank_statement.csv").open("rb"), "text/csv"),
        "settlement_batch": (
            "evil.csv",
            (DEMO_DIR / "settlement_batch.csv").open("rb"),
            "text/csv",
        ),
        "internal_ledger": (
            "evil.csv",
            (DEMO_DIR / "internal_ledger.csv").open("rb"),
            "text/csv",
        ),
    }
    response = client.post("/ingest", files=files)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "validated"
    assert len(body["dataset_id"]) == 32

    # The ingested dataset must be reconcile-able too.
    reconcile_response = client.post("/reconcile", json={"dataset_id": body["dataset_id"]})
    assert reconcile_response.status_code == 200
