from __future__ import annotations

from dataclasses import dataclass
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
from app.services.provider_manager import ProviderManager
from app.services.session_monitor import SessionMonitor


class DummyQueue:
    def __init__(self) -> None:
        self.saved: list[tuple[str, bool | None, bool]] = []

    async def save_job(self, job: JobRecord, *, schedule: bool | None = None, unschedule: bool = False) -> JobRecord:
        self.saved.append((job.state.value, schedule, unschedule))
        return job


class DummyTmux:
    def __init__(self, snapshot: SessionSnapshot) -> None:
        self.snapshot = snapshot
        self.sent_prompts: list[str] = []
        self.cleaned: list[bool] = []
        self.terminated = 0

    async def capture_snapshot(self, job: JobRecord) -> SessionSnapshot | None:
        return self.snapshot

    async def send_prompt(self, job: JobRecord, prompt: str) -> None:
        self.sent_prompts.append(prompt)

    async def terminate_job(self, job: JobRecord) -> None:
        self.terminated += 1

    async def cleanup_job(self, job: JobRecord, *, force: bool = False) -> None:
        self.cleaned.append(force)


class DummyClassifier:
    def __init__(self, result: ClassificationResult) -> None:
        self.result = result

    async def classify(self, job: JobRecord, snapshot: SessionSnapshot) -> ClassificationResult:
        return self.result


class DummyConcurrencyController:
    def __init__(self) -> None:
        self.events: list[ProviderHealthEvent] = []

    async def record_event(self, provider: JobProvider, event: ProviderHealthEvent):
        self.events.append(event)
        return None


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


def make_monitor(snapshot: SessionSnapshot, result: ClassificationResult) -> tuple[SessionMonitor, DummyTmux, DummyQueue, DummyConcurrencyController]:
    settings = Settings(enable_background_worker=False, classifier_enabled=False, test_mode=True)
    queue = DummyQueue()
    tmux = DummyTmux(snapshot)
    concurrency = DummyConcurrencyController()
    monitor = SessionMonitor(
        settings=settings,
        queue=queue,
        tmux_manager=tmux,
        classifier=DummyClassifier(result),
        provider_manager=ProviderManager(),
        concurrency_controller=concurrency,
    )
    return monitor, tmux, queue, concurrency


@pytest.mark.asyncio
async def test_waits_for_provider_readiness_before_prompt_injection() -> None:
    job = make_job(JobState.WAITING_FOR_PROVIDER_READY)
    snapshot = SessionSnapshot(tmux_target="ai-launcher-manager:job-1", recent_output="Welcome")
    result = ClassificationResult(
        state=ClassificationState.READY_FOR_PROMPT,
        confidence=0.9,
        reason="Provider is ready",
        suggested_action=SuggestedAction.SEND_PROMPT,
        provider_ready=True,
        prompt_accepted=False,
    )
    monitor, tmux, _, _ = make_monitor(snapshot, result)

    await monitor.inspect_job(job)

    assert tmux.sent_prompts == ["Investigate the failure"]
    assert job.state == JobState.SENDING_PROMPT
    assert job.prompt_attempt_count == 1


@pytest.mark.asyncio
async def test_retries_prompt_delivery_if_sent_too_early() -> None:
    job = make_job(JobState.SENDING_PROMPT)
    job.prompt_attempt_count = 1
    job.prompt_sent_at = utcnow() - timedelta(seconds=30)
    snapshot = SessionSnapshot(tmux_target="ai-launcher-manager:job-1", recent_output="Still at welcome screen")
    result = ClassificationResult(
        state=ClassificationState.PROMPT_DELIVERY_FAILED,
        confidence=0.9,
        reason="Prompt was not accepted",
        suggested_action=SuggestedAction.RETRY_SEND_PROMPT,
        provider_ready=True,
        prompt_accepted=False,
    )
    monitor, tmux, _, _ = make_monitor(snapshot, result)

    await monitor.inspect_job(job)

    assert tmux.sent_prompts == ["Investigate the failure"]
    assert job.prompt_attempt_count == 2
    assert job.state == JobState.SENDING_PROMPT


@pytest.mark.asyncio
async def test_claude_rate_limit_schedules_ai_selected_recovery() -> None:
    job = make_job(JobState.RUNNING, provider=JobProvider.CLAUDE)
    job.prompt_confirmed_at = utcnow()
    retry_at = utcnow() + timedelta(hours=5)
    snapshot = SessionSnapshot(tmux_target="ai-launcher-manager:job-1", recent_output="Usage limit reached")
    result = ClassificationResult(
        state=ClassificationState.RATE_LIMITED,
        confidence=0.95,
        reason="Claude is rate limited until later",
        suggested_action=SuggestedAction.SCHEDULE_RETRY,
        provider_ready=True,
        prompt_accepted=True,
        recovery_action=RecoveryAction.SEND_CONTINUE_MESSAGE,
        retry_at=retry_at,
    )
    monitor, tmux, queue, concurrency = make_monitor(snapshot, result)

    await monitor.inspect_job(job)

    assert job.state == JobState.RATE_LIMITED
    assert job.next_retry_at == retry_at
    assert job.active_prompt == ProviderManager.CONTINUE_MESSAGE
    assert tmux.terminated == 0
    assert concurrency.events == [ProviderHealthEvent.RATE_LIMITED]
    assert queue.saved[-1][1] is True


@pytest.mark.asyncio
async def test_completed_jobs_cleanup_tmux_window() -> None:
    job = make_job(JobState.RUNNING)
    snapshot = SessionSnapshot(tmux_target="ai-launcher-manager:job-1", recent_output="done")
    result = ClassificationResult(
        state=ClassificationState.COMPLETED,
        confidence=0.99,
        reason="Work is complete",
        suggested_action=SuggestedAction.MARK_COMPLETED,
        provider_ready=True,
        prompt_accepted=True,
    )
    monitor, tmux, _, concurrency = make_monitor(snapshot, result)

    await monitor.inspect_job(job)

    assert job.state == JobState.COMPLETED
    assert tmux.cleaned == [True]
    assert concurrency.events == [ProviderHealthEvent.COMPLETED]
