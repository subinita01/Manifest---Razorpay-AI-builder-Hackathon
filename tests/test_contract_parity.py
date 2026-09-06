"""Contract-parity test.

app/streamlit_app.py calls backend.services.reconcile_service.reconcile()
in-process; an external API client calls the exact same function through
POST /reconcile over HTTP. Both paths already share that one function --
this test doesn't prove that (it's true by inspection) so much as it
guards against someone changing that fact later: if routes.py ever stops
calling reconcile() and hand-rolls the pipeline call differently, or if
reconcile() grows a parameter Streamlit sets that the API's ReconcileRequest
schema doesn't expose, this is the test that would actually catch it --
nothing else in the suite compares the two entry points against each other.

Distinct explicit idempotency keys are used for the two calls specifically
so each one is independently computed rather than one hitting the other's
idempotency cache -- see reconcile_service.compute_idempotency_key, which
would otherwise treat two calls with identical (dataset_id, use_llm,
fuzzy_threshold) and no explicit key as the same cached run.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import backend.db as db_module
from backend.services.reconcile_service import reconcile
from tests.conftest import TEST_API_KEY

_COMPARABLE_RUN_FIELDS = [
    "total_input_rows",
    "matched_row_count",
    "needs_review_row_count",
    "exception_row_count",
    "seed",
    "git_sha",
    "config_hash",
    "fuzzy_threshold",
]


def test_http_and_in_process_entry_points_persist_identical_results(client: TestClient):
    conn = db_module.get_connection()

    # In-process path: exactly what app/streamlit_app.py's Run tab does.
    in_process_run_id = reconcile(
        conn,
        dataset_id="demo",
        use_llm=False,
        fuzzy_threshold=0.90,
        idempotency_key="contract-test-in-process",
    )

    # HTTP path: exactly what an external API client does.
    response = client.post(
        "/reconcile",
        json={"dataset_id": "demo", "use_llm": False, "fuzzy_threshold": 0.90},
        headers={"Idempotency-Key": "contract-test-http"},
    )
    assert response.status_code == 200
    http_run_id = response.json()["run_id"]

    assert in_process_run_id != http_run_id  # two independently computed runs, not a cache hit

    in_process_summary = db_module.get_run(conn, in_process_run_id)
    # The HTTP path is authenticated as TEST_API_KEY (tests/conftest.py's
    # client fixture), which is now also a tenant boundary -- its run was
    # saved with tenant_id=TEST_API_KEY, not tenant_id=None, so the lookup
    # must match that or get_run correctly (and separately) proves nothing.
    http_summary = db_module.get_run(conn, http_run_id, tenant_id=TEST_API_KEY)
    for field in _COMPARABLE_RUN_FIELDS:
        assert (
            in_process_summary[field] == http_summary[field]
        ), f"{field}: in-process={in_process_summary[field]!r} vs http={http_summary[field]!r}"

    # exception_id is content-derived (core/matching/stage6_classify.py:
    # f"exc_{code}_{key}"), not random, so a deterministic pipeline run
    # produces byte-identical exception_ids across separate invocations --
    # sorting just makes the comparison order-independent, not the equality.
    in_process_exceptions = sorted(
        db_module.get_exceptions(conn, in_process_run_id), key=lambda e: e["exception_id"]
    )
    http_exceptions = sorted(
        db_module.get_exceptions(conn, http_run_id), key=lambda e: e["exception_id"]
    )
    assert in_process_exceptions == http_exceptions

    in_process_bridges = sorted(
        db_module.get_bridge_utrs(conn, in_process_run_id), key=lambda b: b["settlement_utr"]
    )
    http_bridges = sorted(
        db_module.get_bridge_utrs(conn, http_run_id), key=lambda b: b["settlement_utr"]
    )
    assert in_process_bridges == http_bridges
