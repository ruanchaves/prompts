from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=3, ge=1, le=20)
    initial_backoff_seconds: int = Field(default=30, ge=1, le=86_400)
    max_backoff_seconds: int = Field(default=600, ge=1, le=86_400)
    multiplier: float = Field(default=2.0, ge=1.0, le=10.0)
    cooldown_seconds: int = Field(default=60, ge=0, le=86_400)

    def backoff_for_attempt(self, attempt_count: int) -> int:
        exponent = max(0, attempt_count - 1)
        backoff = int(self.initial_backoff_seconds * (self.multiplier**exponent))
        backoff = min(backoff, self.max_backoff_seconds)
        return backoff + self.cooldown_seconds
