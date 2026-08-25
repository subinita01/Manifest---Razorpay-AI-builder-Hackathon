"""Shared display formatting: monospace numbers, right-aligned, thousands
separators, two decimals -- a finance tool, not a dashboard template.
"""

from __future__ import annotations

from decimal import Decimal

MONOSPACE_CSS = """
<style>
.manifest-mono {
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    text-align: right;
    white-space: nowrap;
}
div[data-testid="stMetricValue"] {
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
}
</style>
"""


def format_money(value) -> str:
    if value is None:
        return "-"
    return f"{Decimal(str(value)):,.2f}"


def format_pct(value: float) -> str:
    return f"{value * 100:,.1f}%"


def format_int(value: int) -> str:
    return f"{value:,}"
