from __future__ import annotations

import asyncio

from app.core.config import Settings
from app.models.jobs import JobState, MONITORED_JOB_STATES, WorkerHeartbeat, utcnow
from app.services.redis_queue import RedisQueue
from app.services.recovery import RecoveryService
from app.services.session_monitor import SessionMonitor
from app.services.tmux_manager import TmuxManager
from app.utils.logging import get_logger


class WorkerService:
    def __init__(
        self,
        settings: Settings,
        queue: RedisQueue,
        tmux_manager: TmuxManager,
        session_monitor: SessionMonitor,
        recovery: RecoveryService,
    ) -> None:
        self.settings = settings
        self.queue = queue
        self.tmux_manager = tmux_manager
        self.session_monitor = session_monitor
        self.recovery = recovery
        self.stop_event = asyncio.Event()
        self.tasks: list[asyncio.Task[None]] = []
        self.logger = get_logger("ai_launcher_manager.worker")

    async def start(self) -> None:
        await self.recovery.reconcile()
        self.tasks = [
            asyncio.create_task(self._scheduler_loop(), name="scheduler-loop"),
            asyncio.create_task(self._monitor_loop(), name="monitor-loop"),
            asyncio.create_task(self._heartbeat_loop(), name="heartbeat-loop"),
        ]

    async def stop(self) -> None:
        self.stop_event.set()
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)

    async def _scheduler_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                await self._launch_ready_jobs()
            except Exception as exc:  # pragma: no cover - safety net
                self.logger.exception("scheduler loop error: %s", exc)
            await asyncio.sleep(self.settings.scheduler_poll_interval_seconds)

    async def _monitor_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                jobs = await self.queue.list_jobs_by_states(MONITORED_JOB_STATES)
                for job in jobs:
                    await self.session_monitor.inspect_job(job)
            except Exception as exc:  # pragma: no cover - safety net
                self.logger.exception("monitor loop error: %s", exc)
            await asyncio.sleep(self.settings.monitor_poll_interval_seconds)

    async def _heartbeat_loop(self) -> None:
        while not self.stop_event.is_set():
            active_jobs = await self.queue.count_active_jobs()
            heartbeat = WorkerHeartbeat(
                worker_id=self.settings.worker_id,
                updated_at=utcnow(),
                active_jobs=active_jobs,
                details={"tmux_session_name": self.settings.tmux_session_name},
            )
            await self.queue.record_worker_heartbeat(heartbeat)
            await asyncio.sleep(self.settings.monitor_poll_interval_seconds)

    async def _launch_ready_jobs(self) -> None:
        active_jobs = await self.queue.list_jobs_by_states(MONITORED_JOB_STATES)
        available_slots = max(0, self.settings.max_concurrent_jobs - len(active_jobs))
        if available_slots == 0:
            return

        for _ in range(available_slots):
            job = await self.queue.lease_next_job()
            if job is None:
                return

            job.attempt_count += 1
            if job.started_at is None:
                job.started_at = utcnow()
            job.next_retry_at = None
            job.transition(JobState.STARTING, "Launching job in tmux", "scheduler")
            try:
                session_name, window_name = await self.tmux_manager.launch_job(job)
            except Exception as exc:
                if job.can_retry:
                    job.failure_reason = str(exc)
                    job.transition(JobState.RETRYING, f"Launch failed: {exc}", "scheduler")
                    await self.queue.save_job(job, schedule=True)
                else:
                    job.failure_reason = str(exc)
                    job.transition(JobState.FAILED, f"Launch failed and retry budget exhausted: {exc}", "scheduler")
                    await self.queue.save_job(job, unschedule=True)
                continue

            job.tmux_session = session_name
            job.tmux_window = window_name
            job.failure_reason = None
            job.transition(JobState.RUNNING, "Job launched successfully", "scheduler")
            await self.queue.save_job(job)
