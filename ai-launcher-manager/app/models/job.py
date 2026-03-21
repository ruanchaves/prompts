from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.models.classification import ClassificationResult
from app.models.common import utcnow
from app.models.enums import JobProvider, JobState, RecoveryAction, TERMINAL_JOB_STATES
from app.models.events import JobEvent
from app.models.retry import RetryPolicy


class JobRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    provider: JobProvider
    prompt: str
    priority: int
    retry_policy: RetryPolicy
    metadata: dict[str, Any] = Field(default_factory=dict)
    state: JobState = JobState.QUEUED
    attempt_count: int = 0
    prompt_attempt_count: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    next_retry_at: datetime | None = None
    provider_ready_at: datetime | None = None
    prompt_sent_at: datetime | None = None
    prompt_confirmed_at: datetime | None = None
    last_rate_limit_at: datetime | None = None
    recovery_action: RecoveryAction = RecoveryAction.NONE
    active_prompt: str | None = None
    tmux_session: str | None = None
    tmux_window: str | None = None
    last_output: str = ""
    last_output_hash: str | None = None
    last_output_at: datetime | None = None
    last_classification_at: datetime | None = None
    classifier_result: ClassificationResult | None = None
    failure_reason: str | None = None
    events: list[JobEvent] = Field(default_factory=list)

    @computed_field(return_type=str)
    @property
    def launch_command(self) -> str:
        if self.provider == JobProvider.CODEX:
            return "codex --yolo"
        return "claude --dangerously-skip-permissions"

    def add_event(self, state: JobState, message: str, source: str) -> None:
        self.events = (self.events + [JobEvent(state=state, message=message, source=source)])[-50:]
        self.updated_at = utcnow()

    def transition(self, state: JobState, message: str, source: str) -> None:
        self.state = state
        self.updated_at = utcnow()
        if state in TERMINAL_JOB_STATES:
            self.finished_at = self.updated_at
        self.add_event(state=state, message=message, source=source)

    @property
    def can_retry(self) -> bool:
        return self.attempt_count < self.retry_policy.max_attempts
