"""API-key auth for the protected router in backend/routes.py.

Fail-closed by design: if MANIFEST_API_KEYS is unset, api_key_set is empty
and require_api_key rejects every request, rather than silently letting
everything through because nobody configured a key. This is simple
API-key auth, not user accounts or RBAC -- see SECURITY.md for the
threat this closes.
"""

from __future__ import annotations

from fastapi import Header, HTTPException

from backend.config import get_settings


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    if x_api_key is None or x_api_key not in get_settings().api_key_set:
        raise HTTPException(status_code=401, detail="missing or invalid X-API-Key")
