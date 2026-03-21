from __future__ import annotations

from app.models.jobs import JobRecord, JobState, MONITORED_JOB_STATES, TERMINAL_JOB_STATES, utcnow
from app.services.provider_manager import ProviderManager
from app.services.redis_queue import RedisQueue
from app.services.tmux_manager import TmuxManager
from app.utils.logging import get_logger


class RecoveryService:
    def __init__(
        self,
        queue: RedisQueue,
        tmux_manager: TmuxManager,
        provider_manager: ProviderManager,
    ) -> None:
        self.queue = queue
        self.tmux_manager = tmux_manager
        self.provider_manager = provider_manager
        self.logger = get_logger("ai_launcher_manager.recovery")

    def _restore_monitor_state(self, job: JobRecord) -> JobState:
        if job.state != JobState.WAITING_FOR_CLASSIFIER:
            return job.state
        if job.prompt_confirmed_at is not None:
            return JobState.RUNNING
        if job.prompt_sent_at is not None:
            return JobState.SENDING_PROMPT
        return JobState.WAITING_FOR_PROVIDER_READY

    async def reconcile(self) -> None:
        await self.tmux_manager.ensure_session()
        jobs = await self.queue.rebuild_indexes()
        scheduled_ids = await self.queue.list_scheduled_job_ids()
        managed_windows = await self.tmux_manager.discover_managed_windows()
        now = utcnow()

        for job in jobs:
            if job.state in TERMINAL_JOB_STATES:
                await self.queue.save_job(job, unschedule=True)
                if job.tmux_window and job.tmux_window in managed_windows:
                    await self.tmux_manager.cleanup_job(job, force=True)
                continue

            if job.state == JobState.CANCEL_REQUESTED:
                await self.tmux_manager.terminate_job(job)
                job.next_retry_at = None
                job.failure_reason = None
                job.transition(JobState.CANCELLED, "Recovered pending cancellation after restart", "recovery")
                await self.queue.save_job(job, unschedule=True)
                continue

            if job.state in {JobState.QUEUED, JobState.RETRYING, JobState.RATE_LIMITED}:
                if job.job_id not in scheduled_ids:
                    if job.next_retry_at is None:
                        job.next_retry_at = now
                    job.add_event(job.state, "Recovered scheduled job after restart", "recovery")
                    await self.queue.save_job(job, schedule=True)
                continue

            if job.state in MONITORED_JOB_STATES or job.state == JobState.WAITING_FOR_CLASSIFIER:
                restored_state = self._restore_monitor_state(job)
                if restored_state != job.state:
                    job.state = restored_state
                    job.add_event(
                        restored_state,
                        f"Recovered interrupted classification as {restored_state.value}",
                        "recovery",
                    )
                if job.tmux_window and job.tmux_window in managed_windows:
                    job.add_event(job.state, "Recovered active tmux window after restart", "recovery")
                    await self.queue.save_job(job)
                    continue

                if job.can_retry:
                    job.next_retry_at = now
                    job.failure_reason = "Lost tmux window during recovery"
                    job.active_prompt = job.active_prompt or self.provider_manager.default_prompt_for_job(job)
                    job.transition(JobState.RETRYING, "Active window missing during restart; requeued", "recovery")
                    await self.queue.save_job(job, schedule=True)
                else:
                    job.failure_reason = "Lost tmux window during recovery"
                    job.transition(JobState.FAILED, "Active window missing during restart; retry budget exhausted", "recovery")
                    await self.queue.save_job(job, unschedule=True)

        tracked_windows = {job.tmux_window for job in jobs if job.tmux_window}
        orphaned = managed_windows - tracked_windows
        if orphaned:
            self.logger.warning("Found orphaned managed tmux windows: %s", ", ".join(sorted(orphaned)))
