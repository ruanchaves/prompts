"""Tests for MonitorOrchestrator in isolation.

These exercise the orchestrator directly (without going through
SessionMonitor.inspect_job) so that state-transition logic is tested
independently of snapshot capture and classification scheduling.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.config import Settings
from app.models.jobs import (
    ClassificationResult,
    ClassificationState,
    JobProvider,
    JobRecord,
    JobState,
    ProviderHealthEvent,
    RecoveryAction,
    RetryPolicy,
    SessionSnapshot,
    SuggestedAction,
    utcnow,
)
from app.services.monitor_orchestrator import MonitorOrchestrator
from app.services.provider_manager import ProviderManager


# ------------------------------------------------------------------
# Test doubles
# ------------------------------------------------------------------

class DummyQueue:
    def __init__(self) -> None:
        self.saved: list[tuple[str, bool | None, bool]] = []

    async def save_job(self, job: JobRecord, *, schedule: bool | None = None, unschedule: bool = False) -> JobRecord:
        self.saved.append((job.state.value, schedule, unschedule))
        return job


class DummyTmux:
    def __init__(self) -> None:
        self.sent_prompts: list[str] = []
        self.cleaned: list[bool] = []
        self.terminated = 0

    async def send_prompt(self, job: JobRecord, prompt: str) -> None:
        self.sent_prompts.append(prompt)

    async def terminate_job(self, job: JobRecord) -> None:
        self.terminated += 1

    async def cleanup_job(self, job: JobRecord, *, force: bool = False) -> None:
        self.cleaned.append(force)


class DummyConcurrencyController:
    def __init__(self) -> None:
        self.events: list[ProviderHealthEvent] = []

    async def record_event(self, provider: JobProvider, event: ProviderHealthEvent):
        self.events.append(event)
        return None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def make_job(state: JobState, provider: JobProvider = JobProvider.CODEX) -> JobRecord:
    return JobRecord(
        job_id="job-1",
        provider=provider,
        prompt="Investigate the failure",
        active_prompt="Investigate the failure",
        priority=50,
        retry_policy=RetryPolicy(),
        state=state,
        tmux_session="ai-launcher-manager",
        tmux_window="job-job-1",
    )


def make_snapshot() -> SessionSnapshot:
    return SessionSnapshot(tmux_target="ai-launcher-manager:job-1", recent_output="output")


def make_orchestrator() -> tuple[MonitorOrchestrator, DummyTmux, DummyQueue, DummyConcurrencyController]:
    settings = Settings(enable_background_worker=False, classifier_enabled=False, test_mode=True)
    queue = DummyQueue()
    tmux = DummyTmux()
    concurrency = DummyConcurrencyController()
    orchestrator = MonitorOrchestrator(
        settings=settings,
        queue=queue,
        tmux_manager=tmux,
        provider_manager=ProviderManager(),
        concurrency_controller=concurrency,
    )
    return orchestrator, tmux, queue, concurrency


# ------------------------------------------------------------------
# Cancellation
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_cancellation_terminates_and_transitions() -> None:
    orchestrator, tmux, queue, concurrency = make_orchestrator()
    job = make_job(JobState.CANCEL_REQUESTED)

    result = await orchestrator.handle_cancellation(job)

    assert result is job
    assert tmux.terminated == 1
    assert job.state == JobState.CANCELLED
    assert job.next_retry_at is None
    assert job.failure_reason is None
    assert job.recovery_action == RecoveryAction.NONE
    assert queue.saved[-1] == ("cancelled", None, True)
    assert concurrency.events == []


# ------------------------------------------------------------------
# apply_classification
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_completed_cleans_up_and_records_event() -> None:
    orchestrator, tmux, queue, concurrency = make_orchestrator()
    job = make_job(JobState.RUNNING)
    snapshot = make_snapshot()
    result = ClassificationResult(
        state=ClassificationState.COMPLETED,
        confidence=0.99,
        reason="Work is complete",
        suggested_action=SuggestedAction.MARK_COMPLETED,
        provider_ready=True,
        prompt_accepted=True,
    )

    await orchestrator.apply_classification(job, snapshot, result, JobState.RUNNING)

    assert job.state == JobState.COMPLETED
    assert tmux.cleaned == [True]
    assert concurrency.events == [ProviderHealthEvent.COMPLETED]
    assert queue.saved[-1] == ("completed", None, True)


@pytest.mark.asyncio
async def test_failed_with_retries_transitions_to_retrying() -> None:
    orchestrator, tmux, queue, concurrency = make_orchestrator()
    job = make_job(JobState.RUNNING)
    snapshot = make_snapshot()
    result = ClassificationResult(
        state=ClassificationState.FAILED,
        confidence=0.9,
        reason="Something broke",
        suggested_action=SuggestedAction.MARK_FAILED,
        provider_ready=True,
        prompt_accepted=True,
    )

    await orchestrator.apply_classification(job, snapshot, result, JobState.RUNNING)

    assert job.state == JobState.RETRYING
    assert job.failure_reason == "Something broke"
    assert tmux.terminated == 1
    assert concurrency.events == [ProviderHealthEvent.FAILED]
    assert queue.saved[-1][1] is True  # scheduled


@pytest.mark.asyncio
async def test_failed_without_retries_transitions_to_failed() -> None:
    orchestrator, tmux, queue, concurrency = make_orchestrator()
    job = make_job(JobState.RUNNING)
    job.attempt_count = job.retry_policy.max_attempts  # exhaust retries
    snapshot = make_snapshot()
    result = ClassificationResult(
        state=ClassificationState.FAILED,
        confidence=0.9,
        reason="Something broke",
        suggested_action=SuggestedAction.MARK_FAILED,
        provider_ready=True,
        prompt_accepted=True,
    )

    await orchestrator.apply_classification(job, snapshot, result, JobState.RUNNING)

    assert job.state == JobState.FAILED
    assert tmux.cleaned == [True]


@pytest.mark.asyncio
async def test_stuck_without_retries_transitions_to_stuck() -> None:
    orchestrator, tmux, queue, concurrency = make_orchestrator()
    job = make_job(JobState.RUNNING)
    job.attempt_count = job.retry_policy.max_attempts
    snapshot = make_snapshot()
    result = ClassificationResult(
        state=ClassificationState.STUCK,
        confidence=0.85,
        reason="No progress",
        suggested_action=SuggestedAction.MARK_FAILED,
        provider_ready=True,
        prompt_accepted=True,
    )

    await orchestrator.apply_classification(job, snapshot, result, JobState.RUNNING)

    assert job.state == JobState.STUCK
    assert concurrency.events == [ProviderHealthEvent.STUCK]


@pytest.mark.asyncio
async def test_rate_limited_schedules_retry() -> None:
    orchestrator, tmux, queue, concurrency = make_orchestrator()
    job = make_job(JobState.RUNNING, provider=JobProvider.CLAUDE)
    job.prompt_confirmed_at = utcnow()
    retry_at = utcnow() + timedelta(hours=5)
    snapshot = make_snapshot()
    result = ClassificationResult(
        state=ClassificationState.RATE_LIMITED,
        confidence=0.95,
        reason="Claude is rate limited",
        suggested_action=SuggestedAction.SCHEDULE_RETRY,
        provider_ready=True,
        prompt_accepted=True,
        recovery_action=RecoveryAction.SEND_CONTINUE_MESSAGE,
        retry_at=retry_at,
    )

    await orchestrator.apply_classification(job, snapshot, result, JobState.RUNNING)

    assert job.state == JobState.RATE_LIMITED
    assert job.next_retry_at == retry_at
    assert job.active_prompt == ProviderManager.CONTINUE_MESSAGE
    assert tmux.terminated == 0
    assert concurrency.events == [ProviderHealthEvent.RATE_LIMITED]
    assert queue.saved[-1][1] is True


@pytest.mark.asyncio
async def test_rate_limited_relaunch_terminates_session() -> None:
    orchestrator, tmux, queue, concurrency = make_orchestrator()
    job = make_job(JobState.RUNNING, provider=JobProvider.CODEX)
    snapshot = make_snapshot()
    result = ClassificationResult(
        state=ClassificationState.RATE_LIMITED,
        confidence=0.9,
        reason="Rate limited",
        suggested_action=SuggestedAction.SCHEDULE_RETRY,
        provider_ready=True,
        prompt_accepted=True,
        recovery_action=RecoveryAction.RELAUNCH_PROVIDER,
    )

    await orchestrator.apply_classification(job, snapshot, result, JobState.RUNNING)

    assert job.state == JobState.RATE_LIMITED
    assert tmux.terminated == 1


@pytest.mark.asyncio
async def test_ready_for_prompt_sends_prompt() -> None:
    orchestrator, tmux, queue, concurrency = make_orchestrator()
    job = make_job(JobState.WAITING_FOR_PROVIDER_READY)
    snapshot = make_snapshot()
    result = ClassificationResult(
        state=ClassificationState.READY_FOR_PROMPT,
        confidence=0.9,
        reason="Provider is ready",
        suggested_action=SuggestedAction.SEND_PROMPT,
        provider_ready=True,
        prompt_accepted=False,
    )

    await orchestrator.apply_classification(job, snapshot, result, JobState.WAITING_FOR_PROVIDER_READY)

    assert tmux.sent_prompts == ["Investigate the failure"]
    assert job.state == JobState.SENDING_PROMPT
    assert job.prompt_attempt_count == 1


@pytest.mark.asyncio
async def test_prompt_accepted_transitions_to_running() -> None:
    orchestrator, tmux, queue, concurrency = make_orchestrator()
    job = make_job(JobState.SENDING_PROMPT)
    job.prompt_attempt_count = 1
    job.prompt_sent_at = utcnow()
    snapshot = make_snapshot()
    result = ClassificationResult(
        state=ClassificationState.RUNNING,
        confidence=0.9,
        reason="Prompt accepted",
        suggested_action=SuggestedAction.CONTINUE_MONITORING,
        provider_ready=True,
        prompt_accepted=True,
    )

    await orchestrator.apply_classification(job, snapshot, result, JobState.SENDING_PROMPT)

    assert job.state == JobState.RUNNING
    assert job.prompt_confirmed_at is not None
    assert job.active_prompt is None


@pytest.mark.asyncio
async def test_prompt_delivery_failed_retries_after_timeout() -> None:
    orchestrator, tmux, queue, concurrency = make_orchestrator()
    job = make_job(JobState.SENDING_PROMPT)
    job.prompt_attempt_count = 1
    job.prompt_sent_at = utcnow() - timedelta(seconds=30)
    snapshot = make_snapshot()
    result = ClassificationResult(
        state=ClassificationState.PROMPT_DELIVERY_FAILED,
        confidence=0.9,
        reason="Prompt was not accepted",
        suggested_action=SuggestedAction.RETRY_SEND_PROMPT,
        provider_ready=True,
        prompt_accepted=False,
    )

    await orchestrator.apply_classification(job, snapshot, result, JobState.SENDING_PROMPT)

    assert tmux.sent_prompts == ["Investigate the failure"]
    assert job.prompt_attempt_count == 2
    assert job.state == JobState.SENDING_PROMPT


@pytest.mark.asyncio
async def test_prompt_delivery_failed_within_timeout_stays_sending() -> None:
    orchestrator, tmux, queue, concurrency = make_orchestrator()
    job = make_job(JobState.SENDING_PROMPT)
    job.prompt_attempt_count = 1
    job.prompt_sent_at = utcnow() - timedelta(seconds=1)  # within timeout
    snapshot = make_snapshot()
    result = ClassificationResult(
        state=ClassificationState.PROMPT_DELIVERY_FAILED,
        confidence=0.9,
        reason="Prompt was not accepted",
        suggested_action=SuggestedAction.RETRY_SEND_PROMPT,
        provider_ready=True,
        prompt_accepted=False,
    )

    await orchestrator.apply_classification(job, snapshot, result, JobState.SENDING_PROMPT)

    assert tmux.sent_prompts == []  # no retry yet
    assert job.state == JobState.SENDING_PROMPT


@pytest.mark.asyncio
async def test_prompt_delivery_exhausted_marks_failed() -> None:
    orchestrator, tmux, queue, concurrency = make_orchestrator()
    job = make_job(JobState.SENDING_PROMPT)
    job.prompt_attempt_count = 10  # over budget
    job.prompt_sent_at = utcnow() - timedelta(seconds=30)
    job.attempt_count = job.retry_policy.max_attempts  # no retries left
    snapshot = make_snapshot()
    result = ClassificationResult(
        state=ClassificationState.PROMPT_DELIVERY_FAILED,
        confidence=0.9,
        reason="Prompt was not accepted",
        suggested_action=SuggestedAction.RETRY_SEND_PROMPT,
        provider_ready=True,
        prompt_accepted=False,
    )

    await orchestrator.apply_classification(job, snapshot, result, JobState.SENDING_PROMPT)

    assert job.state == JobState.FAILED


# ------------------------------------------------------------------
# handle_missing_window
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_window_with_retries_schedules_retry() -> None:
    orchestrator, tmux, queue, concurrency = make_orchestrator()
    job = make_job(JobState.RUNNING)

    result = await orchestrator.handle_missing_window(job)

    assert result is job
    assert job.state == JobState.RETRYING
    assert job.next_retry_at is not None
    assert job.recovery_action == RecoveryAction.RELAUNCH_PROVIDER
    assert queue.saved[-1][1] is True


@pytest.mark.asyncio
async def test_missing_window_without_retries_marks_failed() -> None:
    orchestrator, tmux, queue, concurrency = make_orchestrator()
    job = make_job(JobState.RUNNING)
    job.attempt_count = job.retry_policy.max_attempts

    result = await orchestrator.handle_missing_window(job)

    assert result is job
    assert job.state == JobState.FAILED
    assert tmux.cleaned == [True]
    assert concurrency.events == [ProviderHealthEvent.FAILED]
    assert queue.saved[-1] == ("failed", None, True)
