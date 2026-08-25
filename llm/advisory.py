from __future__ import annotations

from typing import Any


def fallback_narration_classification(narration: str) -> dict[str, Any]:
    return {
        "type": "UNKNOWN",
        "extracted_ref": None,
        "confidence": 0.0,
    }


def fallback_root_cause(explanation: str) -> dict[str, Any]:
    return {
        "explanation": explanation[:60],
        "suggested_action": "Manual review required",
    }


def fallback_adjustment_entry() -> dict[str, Any]:
    return {
        "lines": [{"account": "SUSPENSE_ACCOUNT", "dr": "0.00", "cr": "0.00"}],
        "memo": "Deterministic fallback; no LLM adjustment generated.",
    }
