from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.models.jobs import JobProvider, JobRecord, JobState, RetryPolicy
from app.services.provider_manager import ProviderManager
from app.services.recovery import RecoveryService
from app.services.tmux_manager import TmuxManager, TmuxSettings


class DummyQueue:
    def __init__(self, job: JobRecord) -> None:
        self.job = job
        self.saved: list[tuple[JobState, bool | None, bool]] = []

    async def rebuild_indexes(self) -> list[JobRecord]:
        return [self.job]

    async def list_scheduled_job_ids(self) -> set[str]:
        return set()

    async def save_job(self, job: JobRecord, *, schedule: bool | None = None, unschedule: bool = False) -> JobRecord:
        self.saved.append((job.state, schedule, unschedule))
        self.job = job
        return job


class DummyTmux:
    def __init__(self, windows: set[str] | None = None) -> None:
        self.windows = windows or set()

    async def ensure_session(self) -> None:
        return None

    async def discover_managed_windows(self) -> set[str]:
        return self.windows

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
        queue,
        DummyTmux(),
        ProviderManager(),
    )

    await recovery.reconcile()

    assert job.state == JobState.RETRYING
    assert queue.saved[-1][1] is True


@pytest.mark.asyncio
async def test_recovery_restores_waiting_for_classifier_back_to_readiness_path() -> None:
    job = JobRecord(
        job_id="job-2",
        provider=JobProvider.CLAUDE,
        prompt="Investigate",
        active_prompt="Investigate",
        priority=50,
        retry_policy=RetryPolicy(),
        state=JobState.WAITING_FOR_CLASSIFIER,
        tmux_window="job-job-2",
    )
    queue = DummyQueue(job)
    recovery = RecoveryService(
        queue,
        DummyTmux(windows={"job-job-2"}),
        ProviderManager(),
    )

    await recovery.reconcile()

    assert job.state == JobState.WAITING_FOR_PROVIDER_READY
    assert queue.saved[-1][0] == JobState.WAITING_FOR_PROVIDER_READY


@pytest.mark.asyncio
async def test_tmux_run_without_output_capture_waits_instead_of_communicate(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyProcess:
        def __init__(self) -> None:
            self.returncode = 0
            self.wait_called = False
            self.communicate_called = False

        async def communicate(self) -> tuple[bytes, bytes]:
            self.communicate_called = True
            return b"", b""

        async def wait(self) -> int:
            self.wait_called = True
            return 0

        def kill(self) -> None:
            return None

    process = DummyProcess()

    async def fake_create_subprocess_exec(*args, **kwargs):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    tmux_settings = TmuxSettings(
        tmux_session_name="ai-launcher-manager",
        tmux_history_lines=200,
        tmux_cleanup_on_terminal_state=True,
        app_dir=Path(__file__).resolve().parents[1] / "app",
    )
    manager = TmuxManager(tmux_settings)
    code, stdout, stderr = await manager._run("tmux", "new-session", "-d", capture_output=False)

    assert code == 0
    assert stdout == ""
    assert stderr == ""
    assert process.wait_called is True
    assert process.communicate_called is False


@pytest.mark.asyncio
async def test_tmux_launch_job_does_not_pass_codex_prompt_via_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    tmux_settings = TmuxSettings(
        tmux_session_name="ai-launcher-manager",
        tmux_history_lines=200,
        tmux_cleanup_on_terminal_state=True,
        app_dir=Path(__file__).resolve().parents[1] / "app",
    )
    manager = TmuxManager(tmux_settings)
    job = JobRecord(
        job_id="job-1",
        provider=JobProvider.CODEX,
        prompt="Review this PR\nFocus on regressions.",
        active_prompt="Review this PR\nFocus on regressions.",
        priority=50,
        retry_policy=RetryPolicy(),
    )

    recorded: dict[str, tuple[str, ...]] = {}

    async def fake_ensure_session() -> None:
        return None

    async def fake_window_exists(window_name: str) -> bool:
        return False

    async def fake_run(*args: str, **kwargs):
        recorded["args"] = args
        return 0, "", ""

    monkeypatch.setattr(manager, "ensure_session", fake_ensure_session)
    monkeypatch.setattr(manager, "window_exists", fake_window_exists)
    monkeypatch.setattr(manager, "_run", fake_run)

    await manager.launch_job(job)

    assert all(not arg.startswith("AILM_PROMPT=") for arg in recorded["args"])
