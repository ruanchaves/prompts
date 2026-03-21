"""Pydantic models used across the service.

All models are defined in focused sub-modules and re-exported here for
convenience.  Existing imports from ``app.models.jobs`` continue to work
via the backward-compatible shim in that module.
"""

from app.models.api import (
    HealthResponse,
    JobCreateRequest,
    JobsListResponse,
    MetricsResponse,
)
from app.models.classification import ClassificationResult
from app.models.common import utcnow
from app.models.concurrency import ProviderConcurrencyRecord
from app.models.enums import (
    ClassificationState,
    JobProvider,
    JobState,
    MONITORED_JOB_STATES,
    ProviderHealthEvent,
    QUEUE_ELIGIBLE_JOB_STATES,
    RecoveryAction,
    SuggestedAction,
    TERMINAL_JOB_STATES,
)
from app.models.events import JobEvent
from app.models.job import JobRecord
from app.models.retry import RetryPolicy
from app.models.session import SessionSnapshot
from app.models.worker import WorkerHeartbeat

__all__ = [
    "ClassificationResult",
    "ClassificationState",
    "HealthResponse",
    "JobCreateRequest",
    "JobEvent",
    "JobProvider",
    "JobRecord",
    "JobState",
    "JobsListResponse",
    "MetricsResponse",
    "MONITORED_JOB_STATES",
    "ProviderConcurrencyRecord",
    "ProviderHealthEvent",
    "QUEUE_ELIGIBLE_JOB_STATES",
    "RecoveryAction",
    "RetryPolicy",
    "SessionSnapshot",
    "SuggestedAction",
    "TERMINAL_JOB_STATES",
    "WorkerHeartbeat",
    "utcnow",
]
