"""Prometheus-format metrics for the FastAPI service.

GET /metrics (backend/routes.py's public_router) is deliberately
unauthenticated, like /healthz: a Prometheus scraper doesn't send an
X-API-Key, and nothing exposed here is sensitive -- request counts,
latencies, and reconciliation row counts by disposition, never a
transaction detail, a taxonomy reason, or anything else SECURITY.md's
threat model treats as protected.

HTTP-level metrics are recorded by a middleware in backend/main.py; the
one domain metric (reconciliation outcomes) is recorded directly in
backend/routes.py's do_reconcile, from numbers it has already computed --
no duplicate work, just labeling data that already exists.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

HTTP_REQUESTS = Counter(
    "manifest_http_requests_total",
    "Total HTTP requests handled, by method, path template, and status",
    ["method", "path", "status"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "manifest_http_request_duration_seconds",
    "HTTP request duration in seconds, by method and path template",
    ["method", "path"],
)

RECONCILE_ROWS = Counter(
    "manifest_reconcile_rows_total",
    "Rows reported by a /reconcile response, by dataset and disposition. "
    "Counts every successful response, including idempotent replays of an "
    "already-computed run -- this measures what the API reported to "
    "callers, not distinct pipeline computations.",
    ["dataset_id", "disposition"],
)


def render_latest() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
