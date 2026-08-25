"""Config loading for MANIFEST core. No env secrets, no network calls.

config/tds_code_map.yaml and config/tds_rates.yaml are the single source of
truth for TDS code mappings; corrections belong there, never in code.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from core.models import MoneyDecimal

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


class UnknownTDSCodeError(KeyError):
    """Raised when a TDS legacy section or new code has no config entry."""


class TDSCodeMapEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legacy_section: str
    new_code: str
    description: str
    effective_from: str
    verified: bool


class TDSRateEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rate_with_pan: MoneyDecimal
    rate_without_pan: MoneyDecimal
    threshold: MoneyDecimal
    verified: bool


@functools.lru_cache(maxsize=1)
def _load_code_map_entries() -> tuple[TDSCodeMapEntry, ...]:
    path = CONFIG_DIR / "tds_code_map.yaml"
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return tuple(TDSCodeMapEntry(**entry) for entry in raw.get("entries", []))


@functools.lru_cache(maxsize=1)
def _load_rates() -> dict[str, TDSRateEntry]:
    path = CONFIG_DIR / "tds_rates.yaml"
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return {code: TDSRateEntry(**entry) for code, entry in raw.get("rates", {}).items()}


@functools.lru_cache(maxsize=1)
def load_settings() -> dict[str, Any]:
    path = CONFIG_DIR / "settings.yaml"
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


@functools.lru_cache(maxsize=1)
def load_chart_of_accounts() -> list[str]:
    path = CONFIG_DIR / "chart_of_accounts.yaml"
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return list(raw.get("accounts", []))


def lookup_new_code(legacy_section: str) -> TDSCodeMapEntry:
    """Return the config entry mapping a legacy section to its new code.

    Raises UnknownTDSCodeError rather than returning a silent default.
    """
    for entry in _load_code_map_entries():
        if entry.legacy_section == legacy_section:
            return entry
    raise UnknownTDSCodeError(f"No config entry for legacy section {legacy_section!r}")


def lookup_code_by_new_code(new_code: str) -> TDSCodeMapEntry:
    for entry in _load_code_map_entries():
        if entry.new_code == new_code:
            return entry
    raise UnknownTDSCodeError(f"No config entry for new code {new_code!r}")


def lookup_rate(new_code: str) -> TDSRateEntry:
    """Return the rate schedule for a numeric TDS code.

    Raises UnknownTDSCodeError rather than returning a silent default.
    """
    rates = _load_rates()
    if new_code not in rates:
        raise UnknownTDSCodeError(f"No rate entry for TDS code {new_code!r}")
    return rates[new_code]
