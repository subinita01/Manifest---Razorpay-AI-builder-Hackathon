"""Structured (JSON) logging for backend/ and llm/, so a real log
aggregator can parse fields instead of grepping text. No new dependency --
this is a ~20-line stdlib logging.Formatter, not a library.

LOG_JSON=false switches to plain text for local dev, if the JSON lines are
harder to eyeball than the flags they save.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from backend.config import get_settings


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        correlation_id = getattr(record, "correlation_id", None)
        if correlation_id is not None:
            payload["correlation_id"] = correlation_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging() -> None:
    settings = get_settings()
    handler = logging.StreamHandler()
    handler.setFormatter(
        JSONFormatter()
        if settings.log_json
        else logging.Formatter("%(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger("manifest")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level)
    root.propagate = False
