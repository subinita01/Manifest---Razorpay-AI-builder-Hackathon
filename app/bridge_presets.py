"""Picks which settlement_utr the Bridge tab's selectbox defaults to, and
which one its "doesn't close" preset button jumps to -- pure functions over
backend.db.get_bridge_utrs()'s output so the picking logic is testable
without a live DuckDB connection or Streamlit session.
"""

from __future__ import annotations

from typing import Any


def pick_clean_default(utrs: list[dict[str, Any]]) -> str | None:
    """A settlement that closes with nothing else flagged -- the "boring,
    everything's fine" case the demo should open on."""
    for u in utrs:
        if u["closed"] and u["rate_variance_rule"] is None:
            return u["settlement_utr"]
    for u in utrs:
        if u["closed"]:
            return u["settlement_utr"]
    return utrs[0]["settlement_utr"] if utrs else None


def pick_unresolved_preset(utrs: list[dict[str, Any]]) -> str | None:
    """A settlement whose bridge does NOT close -- the one-click "show me a
    broken one" preset. Falls back to a bridge that closes but carries a
    rate_variance compliance flag (e.g. FEE_VARIANCE) if every bridge in
    this run happens to close cleanly at the money level -- still a real,
    honestly-labelled finding, just not an open residual."""
    for u in utrs:
        if not u["closed"]:
            return u["settlement_utr"]
    for u in utrs:
        if u["rate_variance_rule"] is not None:
            return u["settlement_utr"]
    return None
