from __future__ import annotations

from datetime import datetime

from app.core.config import Settings
from app.models.jobs import (
    ClassificationState,
    JobProvider,
    JobRecord,
    JobState,
    RecoveryAction,
    RetryPolicy,
    SessionSnapshot,
    utcnow,
)
from app.services.provider_manager import ProviderManager
from app.services.session_classifier import HeuristicSessionClassifier


async def test_heuristic_classifier_marks_completed_on_zero_exit() -> None:
    settings = Settings(enable_background_worker=False, classifier_enabled=False, test_mode=True)
    classifier = HeuristicSessionClassifier(settings, ProviderManager())
    job = JobRecord(
        job_id="job-1",
        provider=JobProvider.CODEX,
        prompt="echo hi",
        active_prompt="echo hi",
        priority=50,
        retry_policy=RetryPolicy(),
        state=JobState.RUNNING,
    )
    snapshot = SessionSnapshot(
        observed_at=utcnow(),
        tmux_target="ai-launcher-manager:job-1",
        pane_dead=True,
        exit_code=0,
        recent_output="done\n__AILM_EXIT_CODE__=0",
    )

    result = await classifier.classify(job, snapshot)
    assert result.state == ClassificationState.COMPLETED


async def test_heuristic_classifier_interprets_claude_rate_limit_retry_time() -> None:
    settings = Settings(
        enable_background_worker=False,
        classifier_enabled=False,
        test_mode=True,
        local_timezone="UTC",
    )
    classifier = HeuristicSessionClassifier(settings, ProviderManager())
    job = JobRecord(
        job_id="job-2",
        provider=JobProvider.CLAUDE,
        prompt="continue work",
        active_prompt=None,
        priority=50,
        retry_policy=RetryPolicy(),
        state=JobState.RUNNING,
    )
    snapshot = SessionSnapshot(
        observed_at=utcnow(),
        tmux_target="ai-launcher-manager:job-2",
        recent_output="Claude usage limit reached. Resets at 2pm (UTC)",
    )

    result = await classifier.classify(job, snapshot)
    assert result.state == ClassificationState.RATE_LIMITED
    assert result.recovery_action == RecoveryAction.PRESS_CONTINUE
    assert isinstance(result.retry_at, datetime)
