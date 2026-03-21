from __future__ import annotations

import pytest

from app.core.config import Settings
from app.models.jobs import JobProvider, JobRecord, JobState, RetryPolicy
from app.services.provider_manager import ProviderManager
from app.services.recovery import RecoveryService


class DummyQueue:
    def __init__(self, job: JobRecord) -> None:
        self.job = job
        self.saved: list[tuple[JobState, bool | None, bool]] = []

    async def list_jobs(self, limit: int = 10_000):
        class _Jobs:
            jobs = [self.job]

        return _Jobs()

    async def list_scheduled_job_ids(self) -> set[str]:
        return set()

    async def save_job(self, job: JobRecord, *, schedule: bool | None = None, unschedule: bool = False) -> JobRecord:
        self.saved.append((job.state, schedule, unschedule))
        self.job = job
        return job


class DummyTmux:
    async def ensure_session(self) -> None:
        return None

    async def discover_managed_windows(self) -> set[str]:
        return set()

    async def cleanup_job(self, job: JobRecord, *, force: bool = False) -> None:
        return None


@pytest.mark.asyncio
async def test_recovery_requeues_partially_launched_jobs_without_windows() -> None:
    job = JobRecord(
        job_id="job-1",
        provider=JobProvider.CODEX,
        prompt="Investigate",
        active_prompt="Investigate",
        priority=50,
        retry_policy=RetryPolicy(),
        state=JobState.WAITING_FOR_PROVIDER_READY,
        tmux_window="job-job-1",
    )
    queue = DummyQueue(job)
    recovery = RecoveryService(
        Settings(enable_background_worker=False, classifier_enabled=False, test_mode=True),
        queue,
        DummyTmux(),
        ProviderManager(),
    )

    await recovery.reconcile()

    assert job.state == JobState.RETRYING
    assert queue.saved[-1][1] is True
