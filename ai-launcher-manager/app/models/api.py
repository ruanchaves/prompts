from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.concurrency import ProviderConcurrencyRecord
from app.models.enums import JobProvider
from app.models.job import JobRecord
from app.models.retry import RetryPolicy


class JobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: JobProvider
    prompt: str = Field(min_length=1)
    priority: int = Field(default=50, ge=0, le=100)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    metadata: dict[str, Any] = Field(default_factory=dict)


class JobsListResponse(BaseModel):
    jobs: list[JobRecord]
    total: int


class HealthResponse(BaseModel):
    status: str
    redis: str
    tmux: str
    worker_count: int


class MetricsResponse(BaseModel):
    counts_by_state: dict[str, int]
    total_jobs: int
    provider_concurrency: list[ProviderConcurrencyRecord]
