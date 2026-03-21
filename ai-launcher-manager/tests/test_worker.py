from __future__ import annotations

import asyncio

import pytest

from app.models.jobs import JobProvider, JobRecord, JobState, RetryPolicy
from app.services.provider_manager import ProviderManager
from app.services.worker import WorkerService, WorkerSettings


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
        settings=WorkerSettings(
            scheduler_poll_interval_seconds=3,
            monitor_poll_interval_seconds=5,
            worker_id="host-worker-1",
            worker_execution_target="host",
            tmux_session_name="ai-launcher-manager",
        ),
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
async def test_launch_provider_keeps_codex_on_readiness_path() -> None:
    worker, queue = make_worker()
    job = make_job(JobProvider.CODEX)

    await worker._launch_provider(job)

    assert job.state == JobState.WAITING_FOR_PROVIDER_READY
    assert job.tmux_session == "ai-launcher-manager"
    assert job.tmux_window == "job-job-1"
    assert job.prompt_attempt_count == 0
    assert job.provider_ready_at is None
    assert job.prompt_sent_at is None
    assert job.prompt_confirmed_at is None
    assert job.active_prompt == "Review this change"
    assert queue.saved[-1][0] == JobState.WAITING_FOR_PROVIDER_READY


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


@pytest.mark.asyncio
async def test_worker_wait_for_failure_raises_background_task_error() -> None:
    worker, _ = make_worker()
    worker.failure_future = asyncio.get_running_loop().create_future()

    async def fail() -> None:
        raise RuntimeError("codex classifier blew up")

    task = asyncio.create_task(fail(), name="monitor-loop")
    task.add_done_callback(worker._handle_task_completion)
    await asyncio.sleep(0)

    with pytest.raises(RuntimeError, match="codex classifier blew up"):
        await worker.wait_for_failure()

    assert worker.stop_event.is_set()
