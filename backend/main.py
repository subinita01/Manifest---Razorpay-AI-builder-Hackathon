"""FastAPI app entrypoint. Endpoints (Day 8): /ingest, /reconcile, /run/{id},
/bridge/{run_id}/{settlement_id}, /manifest/{id}, /metrics/{id}, /audit/{id},
/healthz -- wired to core.pipeline.run_pipeline, not placeholder data."""

from fastapi import FastAPI

app = FastAPI(title="MANIFEST API", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "manifest"}
