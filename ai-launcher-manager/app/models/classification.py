from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ClassificationState, RecoveryAction, SuggestedAction


class ClassificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: ClassificationState
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    suggested_action: SuggestedAction
    provider_ready: bool = False
    prompt_accepted: bool = False
    recovery_action: RecoveryAction = RecoveryAction.NONE
    retry_at: datetime | None = None
    source: str = Field(default="heuristic")
