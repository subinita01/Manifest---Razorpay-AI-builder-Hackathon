from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    dataset_id: str = Field(default="demo_dataset")
    use_llm: bool = False


class ReconcileRequest(BaseModel):
    dataset_id: str = Field(default="demo_dataset")
    use_llm: bool = False
    fuzzy_threshold: float = 0.90


class RunStatusResponse(BaseModel):
    run_id: str
    status: str
    summary: dict[str, Any] = Field(default_factory=dict)


class ManifestResponse(BaseModel):
    run_id: str
    exceptions: list[dict[str, Any]] = Field(default_factory=list)


class MetricsResponse(BaseModel):
    run_id: str
    match_rate: float
    precision: float
    unexplained_count: int = 0
