"""API-key auth for the protected router in backend/routes.py.

Fail-closed by design: if MANIFEST_API_KEYS is unset, api_key_labels is
empty and require_api_key rejects every request, rather than silently
letting everything through because nobody configured a key. This is
simple API-key auth, not user accounts or RBAC -- see SECURITY.md for the
threat this closes.

Returns the caller's label (not just None) so an endpoint that wants
caller attribution in the audit log can add
`caller: str = Depends(require_api_key)` to its own signature -- FastAPI
caches a dependency's result per request, so this doesn't run the check
twice even though it's also applied blanket-style at the router level.
"""

from __future__ import annotations

from fastapi import Header, HTTPException

from backend.config import get_settings


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> str:
    labels = get_settings().api_key_labels
    if x_api_key is None or x_api_key not in labels:
        raise HTTPException(status_code=401, detail="missing or invalid X-API-Key")
    return labels[x_api_key]
