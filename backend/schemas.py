from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class IngestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    status: str
    validation: dict[str, Any] = Field(default_factory=dict)


class ReconcileRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    dataset_id: str = Field(min_length=1, max_length=64)
    use_llm: bool = False
    fuzzy_threshold: float = Field(default=0.90, ge=0.0, le=1.0)


class RunStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: str
    summary: dict[str, Any] = Field(default_factory=dict)


class ManifestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    exceptions: list[dict[str, Any]] = Field(default_factory=list)
