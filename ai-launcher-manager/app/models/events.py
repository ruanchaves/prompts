from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.common import utcnow
from app.models.enums import JobState


class JobEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at: datetime = Field(default_factory=utcnow)
    state: JobState
    source: str = "system"
    message: str
