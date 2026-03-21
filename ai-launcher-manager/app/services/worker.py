from __future__ import annotations

import asyncio
from datetime import timedelta

from app.core.config import Settings
from app.models.jobs import (
    JobProvider,
    JobRecord,
    JobState,
    MONITORED_JOB_STATES,
    ProviderHealthEvent,
    RecoveryAction,
    WorkerHeartbeat,
    utcnow,
)
from app.services.concurrency_controller import ConcurrencyController
from app.services.provider_manager import ProviderManager
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
        provider_manager: ProviderManager,
        concurrency_controller: ConcurrencyController,
    ) -> None:
        self.settings = settings
        self.queue = queue
        self.tmux_manager = tmux_manager
        self.session_monitor = session_monitor
        self.recovery = recovery
        self.provider_manager = provider_manager
        self.concurrency_controller = concurrency_controller
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
            limits = {
                state.provider.value: state.current_limit
                for state in await self.concurrency_controller.list_states()
            }
            active_by_provider = {
                provider.value: await self.queue.count_active_jobs_by_provider(provider)
                for provider in JobProvider
            }
            tmux_session_exists = await self.tmux_manager.session_exists()
            heartbeat = WorkerHeartbeat(
                worker_id=self.settings.worker_id,
                updated_at=utcnow(),
                active_jobs=active_jobs,
                details={
                    "execution_target": self.settings.worker_execution_target,
                    "tmux_session_name": self.settings.tmux_session_name,
                    "tmux_session_exists": tmux_session_exists,
                    "provider_limits": limits,
                    "active_by_provider": active_by_provider,
                },
            )
            await self.queue.record_worker_heartbeat(heartbeat)
            await asyncio.sleep(self.settings.monitor_poll_interval_seconds)

    async def _launch_ready_jobs(self) -> None:
        for provider in JobProvider:
            limit = await self.concurrency_controller.get_limit(provider)
            active_jobs = await self.queue.count_active_jobs_by_provider(provider)
            available_slots = max(0, limit - active_jobs)
            if available_slots == 0:
                continue

            for _ in range(available_slots):
                job = await self.queue.lease_next_job(provider)
                if job is None:
                    break
                await self._start_or_resume_job(job)

    async def _start_or_resume_job(self, job: JobRecord) -> None:
        if job.state == JobState.RATE_LIMITED:
            resumed = await self._resume_rate_limited_job(job)
            if resumed:
                return
        await self._launch_provider(job)

    async def _resume_rate_limited_job(self, job: JobRecord) -> bool:
        if not job.tmux_window or not await self.tmux_manager.window_exists(job.tmux_window):
            job.active_prompt = job.active_prompt or self.provider_manager.continue_message_for_job(job)
            job.recovery_action = RecoveryAction.SEND_CONTINUE_MESSAGE
            await self._launch_provider(job)
            return True

        job.next_retry_at = None
        if job.recovery_action == RecoveryAction.PRESS_CONTINUE:
            await self.tmux_manager.press_continue(job)
            job.transition(JobState.RUNNING, "Triggered Claude continue path after rate limit", "scheduler")
            await self.queue.save_job(job)
            return True

        if job.recovery_action == RecoveryAction.SEND_CONTINUE_MESSAGE:
            prompt = job.active_prompt or self.provider_manager.continue_message_for_job(job)
            job.prompt_attempt_count += 1
            job.prompt_sent_at = utcnow()
            await self.tmux_manager.send_prompt(job, prompt)
            job.transition(JobState.SENDING_PROMPT, "Sent post-rate-limit continue message", "scheduler")
            await self.queue.save_job(job)
            return True

        return False

    async def _launch_provider(self, job: JobRecord) -> None:
        job.attempt_count += 1
        job.next_retry_at = None
        job.provider_ready_at = None
        job.prompt_confirmed_at = None
        job.prompt_sent_at = None
        job.prompt_attempt_count = 0
        job.active_prompt = job.active_prompt or self.provider_manager.default_prompt_for_job(job)
        if job.started_at is None:
            job.started_at = utcnow()
        job.transition(JobState.LAUNCHING, f"Launching fixed provider command: {job.launch_command}", "scheduler")
        try:
            session_name, window_name = await self.tmux_manager.launch_job(job)
        except Exception as exc:
            if job.can_retry:
                job.failure_reason = str(exc)
                job.recovery_action = RecoveryAction.RELAUNCH_PROVIDER
                job.next_retry_at = utcnow() + timedelta(
                    seconds=job.retry_policy.backoff_for_attempt(job.attempt_count)
                )
                job.transition(JobState.RETRYING, f"Launch failed: {exc}", "scheduler")
                await self.queue.save_job(job, schedule=True)
            else:
                job.failure_reason = str(exc)
                job.transition(
                    JobState.FAILED,
                    f"Launch failed and retry budget exhausted: {exc}",
                    "scheduler",
                )
                await self.queue.save_job(job, unschedule=True)
            await self.concurrency_controller.record_event(job.provider, ProviderHealthEvent.LAUNCH_FAILED)
            return

        job.tmux_session = session_name
        job.tmux_window = window_name
        job.failure_reason = None
        job.recovery_action = RecoveryAction.NONE
        if self.provider_manager.delivers_initial_prompt_on_launch(job.provider):
            delivered_at = utcnow()
            job.provider_ready_at = delivered_at
            job.prompt_sent_at = delivered_at
            job.prompt_confirmed_at = delivered_at
            job.prompt_attempt_count = 1
            job.active_prompt = None
            job.transition(
                JobState.RUNNING,
                "Provider launched with its initial prompt attached; monitoring execution",
                "scheduler",
            )
            await self.queue.save_job(job)
            return

        job.transition(
            JobState.WAITING_FOR_PROVIDER_READY,
            "Provider launched; waiting for readiness before prompt injection",
            "scheduler",
        )
        await self.queue.save_job(job)
