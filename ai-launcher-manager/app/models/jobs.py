from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobProvider(str, Enum):
    CLAUDE = "claude"
    CODEX = "codex"


class JobState(str, Enum):
    QUEUED = "queued"
    LAUNCHING = "launching"
    WAITING_FOR_PROVIDER_READY = "waiting_for_provider_ready"
    SENDING_PROMPT = "sending_prompt"
    RUNNING = "running"
    WAITING_FOR_CLASSIFIER = "waiting_for_classifier"
    RATE_LIMITED = "rate_limited"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    STUCK = "stuck"
    CANCELLED = "cancelled"


class ClassificationState(str, Enum):
    WAITING_FOR_PROVIDER_READY = "waiting_for_provider_ready"
    READY_FOR_PROMPT = "ready_for_prompt"
    PROMPT_DELIVERY_FAILED = "prompt_delivery_failed"
    RUNNING = "running"
    RATE_LIMITED = "rate_limited"
    COMPLETED = "completed"
    FAILED = "failed"
    STUCK = "stuck"


class SuggestedAction(str, Enum):
    CONTINUE_MONITORING = "continue_monitoring"
    SEND_PROMPT = "send_prompt"
    RETRY_SEND_PROMPT = "retry_send_prompt"
    SCHEDULE_RETRY = "schedule_retry"
    PRESS_CONTINUE = "press_continue"
    SEND_CONTINUE_MESSAGE = "send_continue_message"
    RELAUNCH_PROVIDER = "relaunch_provider"
    MARK_COMPLETED = "mark_completed"
    MARK_FAILED = "mark_failed"


class RecoveryAction(str, Enum):
    NONE = "none"
    PRESS_CONTINUE = "press_continue"
    SEND_CONTINUE_MESSAGE = "send_continue_message"
    RELAUNCH_PROVIDER = "relaunch_provider"


class ProviderHealthEvent(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"
    STUCK = "stuck"
    LAUNCH_FAILED = "launch_failed"


TERMINAL_JOB_STATES = {
    JobState.COMPLETED,
    JobState.FAILED,
    JobState.STUCK,
    JobState.CANCELLED,
}

QUEUE_ELIGIBLE_JOB_STATES = {
    JobState.QUEUED,
    JobState.RETRYING,
    JobState.RATE_LIMITED,
}

MONITORED_JOB_STATES = {
    JobState.LAUNCHING,
    JobState.WAITING_FOR_PROVIDER_READY,
    JobState.SENDING_PROMPT,
    JobState.RUNNING,
    JobState.WAITING_FOR_CLASSIFIER,
}


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


class JobEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at: datetime = Field(default_factory=utcnow)
    state: JobState
    source: str = "system"
    message: str


class SessionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_at: datetime = Field(default_factory=utcnow)
    tmux_target: str
    pane_dead: bool = False
    exit_code: int | None = None
    pane_pid: int | None = None
    pane_current_command: str | None = None
    recent_output: str = ""


class JobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: JobProvider
    prompt: str = Field(min_length=1)
    priority: int = Field(default=50, ge=0, le=100)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    metadata: dict[str, Any] = Field(default_factory=dict)


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


class WorkerHeartbeat(BaseModel):
    worker_id: str
    updated_at: datetime = Field(default_factory=utcnow)
    active_jobs: int = 0
    details: dict[str, Any] = Field(default_factory=dict)
