"""Shared result shape for every stage in the matching cascade.

Every stage returns this same shape so the ablation runner (evaluation/) can
report each stage's marginal contribution generically, without knowing which
stage it is looking at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.models import MatchResult


@dataclass
class StageResult:
    matched: list[MatchResult] = field(default_factory=list)
    residue_bank: list[Any] = field(default_factory=list)
    residue_settlement: list[Any] = field(default_factory=list)
    # Populated only by stages that consume ledger rows (e.g. stage3_order).
    # Left empty by stages that don't touch the ledger, same as residue_bank
    # is left empty by stages that don't touch bank rows.
    residue_ledger: list[Any] = field(default_factory=list)
    ambiguous: list[dict[str, Any]] = field(default_factory=list)
    # A proposal, never a decision. core/pipeline.py must never promote a
    # needs_review entry to matched on its own -- only a human review can.
    needs_review: list[MatchResult] = field(default_factory=list)
    stage_name: str = ""
    elapsed_ms: float = 0.0
