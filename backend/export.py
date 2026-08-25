"""CSV export for the exception manifest.

Every text field is sanitized against CSV formula injection on the way out
(core.normalize.sanitize_cell), same as core.ingest sanitizes on the way
in -- so a malicious payload is neutralised at both ends of the pipeline,
not just wherever it happened to be caught first.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from core.normalize import sanitize_cell

FIELDNAMES = ["exception_id", "taxonomy_code", "severity", "row_ids", "amount_impact", "detail"]


def _sanitize_leaves(value: Any) -> Any:
    """Recurses into dicts/lists so a payload nested inside `detail` gets
    sanitized individually -- stringifying the whole dict first and
    sanitizing that single string is not enough, since the outer repr
    (e.g. "{'narration': '=cmd|...'}") doesn't itself start with a
    dangerous character even though the value it contains does."""
    if isinstance(value, str):
        return sanitize_cell(value)
    if isinstance(value, dict):
        return {k: _sanitize_leaves(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_leaves(v) for v in value]
    return value


def exceptions_to_csv(exceptions: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=FIELDNAMES)
    writer.writeheader()
    for exc in exceptions:
        writer.writerow(
            {
                "exception_id": sanitize_cell(str(exc["exception_id"])),
                "taxonomy_code": sanitize_cell(str(exc["taxonomy_code"])),
                "severity": sanitize_cell(str(exc["severity"])),
                "row_ids": sanitize_cell(",".join(str(r) for r in exc["row_ids"])),
                "amount_impact": str(exc["amount_impact"]),
                "detail": str(_sanitize_leaves(exc["detail"])),
            }
        )
    return buffer.getvalue()
