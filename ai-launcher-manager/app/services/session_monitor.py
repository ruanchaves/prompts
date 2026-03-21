from __future__ import annotations

import hashlib
from datetime import timedelta

from app.core.config import Settings
from app.models.jobs import (
    ClassificationResult,
    ClassificationState,
    JobRecord,
    JobState,
    SessionSnapshot,
    utcnow,
)
from app.services.redis_queue import RedisQueue
from app.services.session_classifier import CompositeSessionClassifier
from app.services.tmux_manager import TmuxManager
from app.utils.logging import get_logger


class SessionMonitor:
    def __init__(
        self,
        settings: Settings,
        queue: RedisQueue,
        tmux_manager: TmuxManager,
        classifier: CompositeSessionClassifier,
    ) -> None:
        self.settings = settings
        self.queue = queue
        self.tmux_manager = tmux_manager
        self.classifier = classifier
        self.logger = get_logger("ai_launcher_manager.monitor")

    async def inspect_job(self, job: JobRecord) -> JobRecord:
        snapshot = await self.tmux_manager.capture_snapshot(job)
        if snapshot is None:
            return await self._handle_missing_window(job)

        current_hash = hashlib.sha256(snapshot.recent_output.encode("utf-8")).hexdigest()
        output_changed = current_hash != job.last_output_hash
        if output_changed:
            job.last_output = snapshot.recent_output[-self.settings.classifier_max_output_chars :]
            job.last_output_hash = current_hash
            job.last_output_at = snapshot.observed_at

        if not self._should_classify(job, snapshot, output_changed):
            await self.queue.save_job(job)
            return job

        previous_state = job.state
        job.state = JobState.WAITING_FOR_CLASSIFIER
        await self.queue.save_job(job)

        result = await self.classifier.classify(job, snapshot)
        job.last_classification_at = utcnow()
        job.classifier_result = result
        await self._apply_classification(job, snapshot, result, previous_state)
        return job

    def _should_classify(self, job: JobRecord, snapshot: SessionSnapshot, output_changed: bool) -> bool:
        if snapshot.pane_dead:
            return True
        if output_changed:
            return True
        if job.last_classification_at is None:
            return True
        elapsed = (snapshot.observed_at - job.last_classification_at).total_seconds()
        return elapsed >= self.settings.classifier_max_interval_seconds

    async def _apply_classification(
        self,
        job: JobRecord,
        snapshot: SessionSnapshot,
        result: ClassificationResult,
        previous_state: JobState,
    ) -> None:
        state_map = {
            ClassificationState.RUNNING: JobState.RUNNING,
            ClassificationState.IDLE: JobState.IDLE,
            ClassificationState.COMPLETED: JobState.COMPLETED,
            ClassificationState.FAILED: JobState.FAILED,
            ClassificationState.STUCK: JobState.STUCK,
        }

        if result.state == ClassificationState.RATE_LIMITED:
            await self._schedule_retry(job, JobState.RATE_LIMITED, result.reason, result.source)
            return

        if result.state == ClassificationState.FAILED:
            if job.can_retry:
                await self._schedule_retry(job, JobState.RETRYING, result.reason, result.source)
                return
            job.failure_reason = result.reason
            self._transition_if_needed(job, JobState.FAILED, result.reason, result.source, previous_state)
            await self.queue.save_job(job, unschedule=True)
            return

        if result.state == ClassificationState.STUCK:
            if job.can_retry:
                await self._schedule_retry(job, JobState.RETRYING, result.reason, result.source)
                return
            job.failure_reason = result.reason
            self._transition_if_needed(job, JobState.STUCK, result.reason, result.source, previous_state)
            await self.queue.save_job(job, unschedule=True)
            return

        next_state = state_map[result.state]
        self._transition_if_needed(job, next_state, result.reason, result.source, previous_state)
        if next_state == JobState.COMPLETED:
            job.failure_reason = None
            await self.queue.save_job(job, unschedule=True)
            await self.tmux_manager.cleanup_job(job)
            return
        await self.queue.save_job(job)

    def _transition_if_needed(
        self,
        job: JobRecord,
        new_state: JobState,
        reason: str,
        source: str,
        previous_state: JobState,
    ) -> None:
        if previous_state != new_state:
            job.transition(new_state, reason, source)
        else:
            job.state = new_state
            job.updated_at = utcnow()

    async def _schedule_retry(self, job: JobRecord, retry_state: JobState, reason: str, source: str) -> None:
        retry_at = utcnow() + timedelta(seconds=job.retry_policy.backoff_for_attempt(job.attempt_count))
        job.next_retry_at = retry_at
        job.failure_reason = reason
        job.transition(retry_state, f"{reason}. Retry scheduled for {retry_at.isoformat()}", source)
        await self.tmux_manager.terminate_job(job)
        await self.queue.save_job(job, schedule=True)

    async def _handle_missing_window(self, job: JobRecord) -> JobRecord:
        if job.can_retry:
            retry_at = utcnow() + timedelta(seconds=job.retry_policy.backoff_for_attempt(job.attempt_count))
            job.next_retry_at = retry_at
            job.failure_reason = "Managed tmux window is missing"
            job.transition(JobState.RETRYING, f"Managed tmux window is missing. Retry scheduled for {retry_at.isoformat()}", "monitor")
            await self.queue.save_job(job, schedule=True)
            return job

        job.failure_reason = "Managed tmux window is missing"
        job.transition(JobState.FAILED, "Managed tmux window disappeared and retry budget is exhausted", "monitor")
        await self.queue.save_job(job, unschedule=True)
        return job
