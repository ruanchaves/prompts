from __future__ import annotations

from app.core.config import Settings
from app.models.jobs import (
    ClassificationState,
    JobProvider,
    JobRecord,
    RetryPolicy,
    SessionSnapshot,
    utcnow,
)
from app.services.session_classifier import HeuristicSessionClassifier


async def test_heuristic_classifier_marks_completed_on_zero_exit() -> None:
    settings = Settings(enable_background_worker=False, classifier_enabled=False, test_mode=True)
    classifier = HeuristicSessionClassifier(settings)
    job = JobRecord(
        job_id="job-1",
        provider=JobProvider.CODEX,
        command="echo hi",
        priority=50,
        retry_policy=RetryPolicy(),
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


async def test_heuristic_classifier_marks_rate_limited() -> None:
    settings = Settings(enable_background_worker=False, classifier_enabled=False, test_mode=True)
    classifier = HeuristicSessionClassifier(settings)
    job = JobRecord(
        job_id="job-2",
        provider=JobProvider.CLAUDE,
        command="claude-code",
        priority=50,
        retry_policy=RetryPolicy(),
    )
    snapshot = SessionSnapshot(
        observed_at=utcnow(),
        tmux_target="ai-launcher-manager:job-2",
        recent_output="429 rate limit exceeded, please try again later",
    )

    result = await classifier.classify(job, snapshot)
    assert result.state == ClassificationState.RATE_LIMITED
