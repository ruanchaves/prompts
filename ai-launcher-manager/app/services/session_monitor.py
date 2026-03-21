from __future__ import annotations

import hashlib

from app.core.config import Settings
from app.models.jobs import (
    JobRecord,
    JobState,
    SessionSnapshot,
    utcnow,
)
from app.services.monitor_orchestrator import MonitorOrchestrator
from app.services.redis_queue import RedisQueue
from app.services.session_classifier import CompositeSessionClassifier
from app.services.tmux_manager import TmuxManager
from app.utils.logging import get_logger


class SessionMonitor:
    """Captures tmux output and decides *when* to classify a job.

    State-transition orchestration (what happens after classification)
    is delegated to :class:`MonitorOrchestrator`.
    """

    def __init__(
        self,
        settings: Settings,
        queue: RedisQueue,
        tmux_manager: TmuxManager,
        classifier: CompositeSessionClassifier,
        orchestrator: MonitorOrchestrator,
    ) -> None:
        self.settings = settings
        self.queue = queue
        self.tmux_manager = tmux_manager
        self.classifier = classifier
        self.orchestrator = orchestrator
        self.logger = get_logger("ai_launcher_manager.monitor")

    async def inspect_job(self, job: JobRecord) -> JobRecord:
        if job.state == JobState.CANCEL_REQUESTED:
            return await self.orchestrator.handle_cancellation(job)

        snapshot = await self.tmux_manager.capture_snapshot(job)
        if snapshot is None:
            return await self.orchestrator.handle_missing_window(job)

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
        await self.orchestrator.apply_classification(job, snapshot, result, previous_state)
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
