"""FastAPI app entrypoint. See SECURITY.md for the threat model behind
every control wired up here."""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.config import get_settings
from backend.logging_config import configure_logging
from backend.routes import limiter, public_router, router
from backend.security import MAX_UPLOAD_BYTES

configure_logging()
logger = logging.getLogger("manifest")

app = FastAPI(title="MANIFEST API", version="0.1.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


def _unhandled_error_response(exc: Exception) -> JSONResponse:
    correlation_id = uuid.uuid4().hex
    logger.exception("unhandled error [correlation_id=%s]", correlation_id)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "correlation_id": correlation_id},
    )


# T8 disclosure: never leak a traceback or exception message to the client.
# The traceback goes to the log only, keyed by a correlation_id the client
# can reference when reporting the issue. This handler alone is not
# sufficient: a plain `@app.middleware("http")` function is a
# BaseHTTPMiddleware under the hood, and a documented Starlette limitation
# means an exception raised downstream of it does not reliably reach a
# generic `@app.exception_handler(Exception)` -- so the middleware below
# also wraps call_next in its own try/except using this same formatter.
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return _unhandled_error_response(exc)


# CORS: configurable via MANIFEST_CORS_ORIGINS (backend/config.py), never a
# wildcard -- defaults to the Streamlit dev origin if unset.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers_and_body_limit(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length is not None and int(content_length) > MAX_UPLOAD_BYTES:
        return JSONResponse(status_code=413, content={"error": "payload_too_large"})

    try:
        response = await call_next(request)
    except Exception as exc:  # noqa: BLE001 -- last-resort catch-all, see docstring above
        return _unhandled_error_response(exc)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


app.include_router(public_router)
app.include_router(router)
