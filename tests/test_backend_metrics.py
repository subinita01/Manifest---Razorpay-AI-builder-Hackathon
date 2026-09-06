"""backend/metrics.py's Counter/Histogram objects register to
prometheus_client's global default registry, shared by every test in the
process -- so these tests assert the *delta* a specific action causes,
never an absolute total, which would be order-dependent on whatever else
in the suite hit these same endpoints first.
"""

from fastapi.testclient import TestClient

from backend.metrics import HTTP_REQUESTS, RECONCILE_ROWS, render_latest


def _counter_value(counter, *label_values) -> float:
    # ._value.get() is prometheus_client's own standard way to read a
    # counter's current value in tests; .labels() creates the labeled
    # child (starting at 0) if it doesn't exist yet, so this never raises
    # for a combination nothing has incremented yet.
    return counter.labels(*label_values)._value.get()


def test_render_latest_returns_prometheus_text_format():
    body, content_type = render_latest()
    assert b"manifest_http_requests_total" in body
    assert "text/plain" in content_type


def test_metrics_endpoint_requires_no_api_key(client: TestClient):
    from backend.main import app

    bare_client = TestClient(app)
    response = bare_client.get("/metrics")
    assert response.status_code == 200
    assert b"manifest_http_requests_total" in response.content


def test_http_requests_counter_increments_on_a_real_request(client: TestClient):
    before = _counter_value(HTTP_REQUESTS, "GET", "/healthz", "200")
    response = client.get("/healthz")
    assert response.status_code == 200
    after = _counter_value(HTTP_REQUESTS, "GET", "/healthz", "200")
    assert after - before == 1


def test_reconcile_success_increments_the_row_disposition_counters(client: TestClient):
    before_matched = _counter_value(RECONCILE_ROWS, "demo", "matched")
    before_review = _counter_value(RECONCILE_ROWS, "demo", "needs_review")
    before_exception = _counter_value(RECONCILE_ROWS, "demo", "exception")

    response = client.post("/reconcile", json={"dataset_id": "demo", "use_llm": False})
    assert response.status_code == 200
    summary = response.json()["summary"]

    assert (
        _counter_value(RECONCILE_ROWS, "demo", "matched") - before_matched
        == summary["matched_row_count"]
    )
    assert (
        _counter_value(RECONCILE_ROWS, "demo", "needs_review") - before_review
        == summary["needs_review_row_count"]
    )
    assert (
        _counter_value(RECONCILE_ROWS, "demo", "exception") - before_exception
        == summary["exception_row_count"]
    )


def test_reconcile_401_does_not_increment_row_disposition_counters(monkeypatch, tmp_path):
    import backend.db as db_module
    from backend.main import app

    monkeypatch.setattr(db_module, "DEFAULT_DB_PATH", tmp_path / "test.duckdb")
    monkeypatch.setenv("MANIFEST_API_KEYS", "priya:priya-key")
    bare_client = TestClient(app)

    before_matched = _counter_value(RECONCILE_ROWS, "demo", "matched")
    response = bare_client.post("/reconcile", json={"dataset_id": "demo"})
    assert response.status_code == 401
    assert _counter_value(RECONCILE_ROWS, "demo", "matched") == before_matched
