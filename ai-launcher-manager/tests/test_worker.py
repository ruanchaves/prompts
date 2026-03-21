from __future__ import annotations

import pytest

from app.core.config import Settings
from app.models.jobs import JobProvider, JobRecord, JobState, RetryPolicy
from app.services.provider_manager import ProviderManager
from app.services.worker import WorkerService


class DummyQueue:
    def __init__(self) -> None:
        self.saved: list[tuple[JobState, bool | None, bool]] = []

    async def save_job(self, job: JobRecord, *, schedule: bool | None = None, unschedule: bool = False) -> JobRecord:
        self.saved.append((job.state, schedule, unschedule))
        return job


class DummyTmux:
    async def launch_job(self, job: JobRecord) -> tuple[str, str]:
        return "ai-launcher-manager", f"job-{job.job_id}"

    async def window_exists(self, window_name: str) -> bool:
        return True

    async def send_prompt(self, job: JobRecord, prompt: str) -> None:
        return None

    async def press_continue(self, job: JobRecord) -> None:
        return None


class DummySessionMonitor:
    async def inspect_job(self, job: JobRecord) -> JobRecord:
        return job


class DummyRecovery:
    async def reconcile(self) -> None:
        return None


class DummyConcurrencyController:
    async def get_limit(self, provider: JobProvider) -> int:
        return 1

    async def list_states(self) -> list[object]:
        return []

    async def record_event(self, provider: JobProvider, event: object) -> None:
        return None


def make_worker() -> tuple[WorkerService, DummyQueue]:
    queue = DummyQueue()
    worker = WorkerService(
        settings=Settings(enable_background_worker=False, classifier_enabled=False, test_mode=True),
        queue=queue,
        tmux_manager=DummyTmux(),
        session_monitor=DummySessionMonitor(),
        recovery=DummyRecovery(),
        provider_manager=ProviderManager(),
        concurrency_controller=DummyConcurrencyController(),
    )
    return worker, queue


def make_job(provider: JobProvider) -> JobRecord:
    return JobRecord(
        job_id="job-1",
        provider=provider,
        prompt="Review this change",
        active_prompt="Review this change",
        priority=50,
        retry_policy=RetryPolicy(),
    )


@pytest.mark.asyncio
async def test_launch_provider_marks_codex_running_immediately() -> None:
    worker, queue = make_worker()
    job = make_job(JobProvider.CODEX)

    await worker._launch_provider(job)

    assert job.state == JobState.RUNNING
    assert job.tmux_session == "ai-launcher-manager"
    assert job.tmux_window == "job-job-1"
    assert job.prompt_attempt_count == 1
    assert job.provider_ready_at is not None
    assert job.prompt_sent_at is not None
    assert job.prompt_confirmed_at is not None
    assert job.active_prompt is None
    assert queue.saved[-1][0] == JobState.RUNNING


@pytest.mark.asyncio
async def test_launch_provider_keeps_claude_on_readiness_path() -> None:
    worker, queue = make_worker()
    job = make_job(JobProvider.CLAUDE)

    await worker._launch_provider(job)

    assert job.state == JobState.WAITING_FOR_PROVIDER_READY
    assert job.prompt_attempt_count == 0
    assert job.provider_ready_at is None
    assert job.prompt_sent_at is None
    assert job.prompt_confirmed_at is None
    assert job.active_prompt == "Review this change"
    assert queue.saved[-1][0] == JobState.WAITING_FOR_PROVIDER_READY
