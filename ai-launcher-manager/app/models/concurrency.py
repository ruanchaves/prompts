from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.common import utcnow
from app.models.enums import JobProvider


class ProviderConcurrencyRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: JobProvider
    current_limit: int
    success_streak: int = 0
    failure_streak: int = 0
    total_completions: int = 0
    total_failures: int = 0
    total_rate_limits: int = 0
    updated_at: datetime = Field(default_factory=utcnow)
