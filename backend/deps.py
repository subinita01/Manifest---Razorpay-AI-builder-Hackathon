"""FastAPI-specific dependencies. Kept separate from backend/db.py, which
stays framework-agnostic -- app/streamlit_app.py and scripts/smoke_test.py
call backend.db directly too, never through FastAPI's dependency system.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator

from fastapi import HTTPException

from backend import db


def get_db_connection() -> Iterator[db.DBConnection]:
    """Yield-style FastAPI dependency: checks a connection out (pooled, if
    DATABASE_URL is set) and returns it when the request finishes, whether
    it succeeded or raised. DuckDB has no pool here -- get_connection()
    opening one fresh file handle per call is already cheap and correct
    for a local embedded file; pooling only matters for Postgres's real
    network connections, which is what backend/db_postgres.py's
    pooled_connection() actually reuses across requests.

    Only the acquisition step is wrapped in try/except, converting a
    failure there into HTTPException(503) -- a real bug caught while
    building this: wrapping the whole function (acquisition *and* the
    yield) also catches whatever the endpoint body itself raises, which
    would misreport an unrelated application error as "database
    unavailable". Endpoint-body exceptions (a 404, a 400, or a genuine
    bug) must propagate unchanged; only "the database itself couldn't be
    reached" becomes a 503, and every route gets that translation now,
    not just /healthz, which is the one route that used to have its own
    try/except for this before this dependency existed."""
    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        try:
            conn = db.get_connection()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="database unavailable") from exc
        yield conn
        return

    from backend.db_postgres import pooled_connection

    cm = pooled_connection(database_url)
    try:
        conn = cm.__enter__()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc

    try:
        yield conn
    except BaseException:
        if not cm.__exit__(*sys.exc_info()):
            raise
    else:
        cm.__exit__(None, None, None)
