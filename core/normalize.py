"""Raw-input normalization: dates, money strings, UTR extraction, CSV safety.

sanitize_cell must only be applied to free-text fields (narration, detail
strings) on ingest and export. Never apply it to a serialized Decimal: a
negative amount like "-123.45" legitimately starts with "-" and must not be
quote-prefixed, or downstream Decimal parsing breaks.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%b-%y")

# The build plan's UTR-extraction spec anchors only on UTR/RTGS/NEFT markers,
# but its own generator spec includes the narration "UPI-SETTLEMENT-{utr}",
# which has no UTR/RTGS/NEFT marker adjacent to the digits. SETTLEMENT is
# added here so that narration format is extractable too; UPI alone is kept
# for the same template's leading marker.
_UTR_PATTERN = re.compile(
    r"(?:UTR|RTGS|NEFT|UPI|SETTLEMENT)[\s\-/:]*(?=[0-9])([A-Z0-9]{8,22})",
    re.IGNORECASE,
)

_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


class UnparseableDate(ValueError):
    """Raised when a date string matches none of the known formats."""


def parse_date(value: str) -> date:
    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise UnparseableDate(f"Cannot parse date: {value!r}")


def parse_money(value: str | None) -> Decimal | None:
    if value is None:
        return None
    text = value.strip()
    if text == "":
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    text = text.replace(",", "")
    amount = Decimal(text)
    return -amount if negative else amount


def extract_utr(narration: str) -> str | None:
    match = _UTR_PATTERN.search(narration.upper())
    if not match:
        return None
    return match.group(1)


def normalize_narration(value: str) -> str:
    text = value.upper()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def sanitize_cell(value: str) -> str:
    """Neutralise CSV formula injection. Free-text fields only; see module docstring."""
    if value and value[0] in _INJECTION_PREFIXES:
        return "'" + value
    return value
