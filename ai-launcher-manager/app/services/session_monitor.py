from __future__ import annotations

import hashlib
from datetime import timedelta

from app.core.config import Settings
from app.models.jobs import (
    ClassificationResult,
    ClassificationState,
    JobProvider,
    JobRecord,
    JobState,
    ProviderHealthEvent,
    RecoveryAction,
    SessionSnapshot,
    SuggestedAction,
    utcnow,
)
from app.services.concurrency_controller import ConcurrencyController
from app.services.provider_manager import ProviderManager
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
        provider_manager: ProviderManager,
        concurrency_controller: ConcurrencyController,
    ) -> None:
        self.settings = settings
        self.queue = queue
        self.tmux_manager = tmux_manager
        self.classifier = classifier
        self.provider_manager = provider_manager
        self.concurrency_controller = concurrency_controller
        self.logger = get_logger("ai_launcher_manager.monitor")

    async def inspect_job(self, job: JobRecord) -> JobRecord:
        if job.state == JobState.CANCEL_REQUESTED:
            await self.tmux_manager.terminate_job(job)
            job.next_retry_at = None
            job.failure_reason = None
            job.recovery_action = RecoveryAction.NONE
            job.transition(JobState.CANCELLED, "Job cancelled by operator and host tmux session terminated", "monitor")
            await self.queue.save_job(job, unschedule=True)
            return job

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
        if result.state == ClassificationState.COMPLETED:
            job.failure_reason = None
            job.active_prompt = None
            job.recovery_action = RecoveryAction.NONE
            self._transition_if_needed(job, JobState.COMPLETED, result.reason, result.source, previous_state)
            await self.queue.save_job(job, unschedule=True)
            await self.tmux_manager.cleanup_job(job, force=True)
            await self.concurrency_controller.record_event(job.provider, ProviderHealthEvent.COMPLETED)
            return

        if result.state == ClassificationState.FAILED:
            await self._handle_failure(job, result.reason, result.source, ProviderHealthEvent.FAILED, previous_state)
            return

        if result.state == ClassificationState.STUCK:
            await self._handle_failure(job, result.reason, result.source, ProviderHealthEvent.STUCK, previous_state)
            return

        if result.state == ClassificationState.RATE_LIMITED:
            await self._schedule_rate_limit_retry(job, result, previous_state)
            return

        if previous_state == JobState.WAITING_FOR_PROVIDER_READY:
            if result.provider_ready or result.state == ClassificationState.READY_FOR_PROMPT:
                await self._send_pending_prompt(job, result.reason, result.source)
                return
            self._transition_if_needed(
                job,
                JobState.WAITING_FOR_PROVIDER_READY,
                result.reason,
                result.source,
                previous_state,
            )
            await self.queue.save_job(job)
            return

        if previous_state == JobState.SENDING_PROMPT:
            prompt_accepted = result.prompt_accepted or (
                job.provider == JobProvider.CLAUDE and result.state == ClassificationState.RUNNING
            )
            if prompt_accepted:
                job.prompt_confirmed_at = utcnow()
                job.active_prompt = None
                self._transition_if_needed(job, JobState.RUNNING, result.reason, result.source, previous_state)
                await self.queue.save_job(job)
                return

            if result.state == ClassificationState.PROMPT_DELIVERY_FAILED or result.suggested_action in {
                SuggestedAction.RETRY_SEND_PROMPT,
                SuggestedAction.SEND_PROMPT,
            }:
                # Only retry after the delivery timeout has elapsed to give
                # the provider time to start processing.  Without this guard,
                # slower providers like Codex receive duplicate pastes because
                # the classifier fires before visible output appears.
                delivery_elapsed = (
                    (utcnow() - job.prompt_sent_at).total_seconds()
                    if job.prompt_sent_at
                    else float("inf")
                )
                if delivery_elapsed < self.settings.prompt_delivery_timeout_seconds:
                    self._transition_if_needed(
                        job, JobState.SENDING_PROMPT, result.reason, result.source, previous_state,
                    )
                    await self.queue.save_job(job)
                    return

                if job.prompt_attempt_count < self.settings.max_prompt_delivery_attempts:
                    await self._send_pending_prompt(job, result.reason, result.source)
                    return

                await self._handle_failure(
                    job,
                    "Prompt delivery failed repeatedly and retry budget is exhausted",
                    "monitor",
                    ProviderHealthEvent.FAILED,
                    previous_state,
                )
                return

            self._transition_if_needed(job, JobState.SENDING_PROMPT, result.reason, result.source, previous_state)
            await self.queue.save_job(job)
            return

        self._transition_if_needed(job, JobState.RUNNING, result.reason, result.source, previous_state)
        await self.queue.save_job(job)

    async def _send_pending_prompt(self, job: JobRecord, reason: str, source: str) -> None:
        prompt = job.active_prompt or self.provider_manager.default_prompt_for_job(job)
        job.provider_ready_at = utcnow()
        job.prompt_attempt_count += 1
        job.prompt_sent_at = utcnow()
        await self.tmux_manager.send_prompt(job, prompt)
        previous_state = job.state
        self._transition_if_needed(
            job,
            JobState.SENDING_PROMPT,
            f"{reason}. Prompt injection attempt {job.prompt_attempt_count}",
            source,
            previous_state,
        )
        await self.queue.save_job(job)

    async def _schedule_rate_limit_retry(
        self,
        job: JobRecord,
        result: ClassificationResult,
        previous_state: JobState,
    ) -> None:
        retry_at = result.retry_at or (utcnow() + timedelta(seconds=job.retry_policy.backoff_for_attempt(job.attempt_count)))
        job.next_retry_at = retry_at
        job.last_rate_limit_at = utcnow()
        job.failure_reason = result.reason
        job.recovery_action = (
            result.recovery_action
            if result.recovery_action != RecoveryAction.NONE
            else self.provider_manager.default_recovery_action(job.provider)
        )
        if job.recovery_action == RecoveryAction.SEND_CONTINUE_MESSAGE:
            job.active_prompt = self.provider_manager.continue_message_for_job(job)
            job.prompt_attempt_count = 0
        elif job.recovery_action == RecoveryAction.RELAUNCH_PROVIDER:
            job.active_prompt = self.provider_manager.default_prompt_for_job(job)
            job.prompt_attempt_count = 0
            await self.tmux_manager.terminate_job(job)

        self._transition_if_needed(
            job,
            JobState.RATE_LIMITED,
            f"{result.reason}. Retry scheduled for {retry_at.isoformat()} via {job.recovery_action.value}",
            result.source,
            previous_state,
        )
        await self.queue.save_job(job, schedule=True)
        await self.concurrency_controller.record_event(job.provider, ProviderHealthEvent.RATE_LIMITED)

    async def _handle_failure(
        self,
        job: JobRecord,
        reason: str,
        source: str,
        event: ProviderHealthEvent,
        previous_state: JobState,
    ) -> None:
        if job.can_retry:
            retry_at = utcnow() + timedelta(seconds=job.retry_policy.backoff_for_attempt(job.attempt_count))
            job.next_retry_at = retry_at
            job.failure_reason = reason
            job.recovery_action = RecoveryAction.RELAUNCH_PROVIDER
            job.active_prompt = self.provider_manager.default_prompt_for_job(job)
            job.prompt_attempt_count = 0
            self._transition_if_needed(
                job,
                JobState.RETRYING,
                f"{reason}. Retry scheduled for {retry_at.isoformat()}",
                source,
                previous_state,
            )
            await self.tmux_manager.terminate_job(job)
            await self.queue.save_job(job, schedule=True)
            await self.concurrency_controller.record_event(job.provider, event)
            return

        job.failure_reason = reason
        terminal_state = JobState.STUCK if event == ProviderHealthEvent.STUCK else JobState.FAILED
        self._transition_if_needed(job, terminal_state, reason, source, previous_state)
        await self.queue.save_job(job, unschedule=True)
        await self.tmux_manager.cleanup_job(job, force=True)
        await self.concurrency_controller.record_event(job.provider, event)

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

    async def _handle_missing_window(self, job: JobRecord) -> JobRecord:
        if job.can_retry:
            retry_at = utcnow() + timedelta(seconds=job.retry_policy.backoff_for_attempt(job.attempt_count))
            job.next_retry_at = retry_at
            job.failure_reason = "Managed tmux window is missing"
            job.recovery_action = RecoveryAction.RELAUNCH_PROVIDER
            job.active_prompt = job.active_prompt or self.provider_manager.default_prompt_for_job(job)
            job.prompt_attempt_count = 0
            job.transition(
                JobState.RETRYING,
                f"Managed tmux window is missing. Retry scheduled for {retry_at.isoformat()}",
                "monitor",
            )
            await self.queue.save_job(job, schedule=True)
            return job

        job.failure_reason = "Managed tmux window is missing"
        job.transition(JobState.FAILED, "Managed tmux window disappeared and retry budget is exhausted", "monitor")
        await self.queue.save_job(job, unschedule=True)
        await self.tmux_manager.cleanup_job(job, force=True)
        await self.concurrency_controller.record_event(job.provider, ProviderHealthEvent.FAILED)
        return job
