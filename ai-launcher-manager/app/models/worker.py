from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.common import utcnow


class WorkerHeartbeat(BaseModel):
    worker_id: str
    updated_at: datetime = Field(default_factory=utcnow)
    active_jobs: int = 0
    details: dict[str, Any] = Field(default_factory=dict)
