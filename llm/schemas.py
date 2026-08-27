"""Pydantic schemas every LLM response is validated against (CLAUDE.md
rule 4). Nothing free-form ever reaches an exception's stored detail --
the LLM's output is coerced into one of these shapes or discarded.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class NarrationType(str, Enum):
    SETTLEMENT = "SETTLEMENT"
    REFUND = "REFUND"
    CHARGEBACK = "CHARGEBACK"
    FEE = "FEE"
    OTHER = "OTHER"
    SUSPICIOUS = "SUSPICIOUS"


class NarrationClassification(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    narration_type: NarrationType
    extracted_reference: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    suspicious: bool = False
    reasoning: str = Field(max_length=200)


class RootCauseNarrative(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    explanation: str = Field(max_length=500)
    suggested_action: str = Field(max_length=200)
    confidence: float = Field(ge=0.0, le=1.0)


class AdjustmentLine(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    account: str
    dr: str = "0.00"
    cr: str = "0.00"


class AdjustmentDraft(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    lines: list[AdjustmentLine] = Field(min_length=1, max_length=10)
    memo: str = Field(max_length=300)


class QueryAnswer(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    answer: str = Field(max_length=1000)
    cited_exception_ids: list[str] = Field(default_factory=list, max_length=20)
