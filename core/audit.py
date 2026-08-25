from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class AuditLogger:
    def __init__(self, log_path: str | Path):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def _hash(self, value: Any) -> str:
        payload = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def read_last_hash(self) -> str:
        if not self.log_path.exists():
            return "genesis"
        with self.log_path.open("r", encoding="utf-8") as handle:
            lines = [line.strip() for line in handle if line.strip()]
        if not lines:
            return "genesis"
        try:
            last = json.loads(lines[-1])
            return str(last.get("hash"))
        except json.JSONDecodeError:
            return "genesis"

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        prev_hash = self.read_last_hash()
        record = {
            "prev_hash": prev_hash,
            "event": event,
            "hash": self._hash({"prev_hash": prev_hash, "event": event}),
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        return record
