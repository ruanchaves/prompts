from __future__ import annotations

from enum import Enum


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
    CANCEL_REQUESTED = "cancel_requested"
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
    JobState.CANCEL_REQUESTED,
}
