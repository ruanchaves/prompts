from __future__ import annotations

import asyncio
from datetime import datetime
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.models.jobs import (
    ClassificationResult,
    ClassificationState,
    JobProvider,
    JobRecord,
    JobState,
    RecoveryAction,
    RetryPolicy,
    SessionSnapshot,
    SuggestedAction,
    utcnow,
)
from app.services.provider_manager import ProviderManager
from app.services.session_classifier import (
    CodexClassifierSettings,
    CodexCliSessionClassifier,
    CompositeClassifierSettings,
    CompositeSessionClassifier,
    HeuristicClassifierSettings,
    HeuristicSessionClassifier,
    SessionClassificationError,
)


def make_codex_settings(tmp_path: Path) -> CodexClassifierSettings:
    prompt_path = tmp_path / "classifier_prompt.md"
    prompt_path.write_text(
        "Return JSON between {marker_start} and {marker_end}.\nSchema:\n{schema}\nContext:\n{context}\n",
        encoding="utf-8",
    )
    schema_path = tmp_path / "classifier_schema.json"
    schema_path.write_text("{\"type\":\"object\"}", encoding="utf-8")
    return CodexClassifierSettings(
        classifier_prompt_path=prompt_path,
        classifier_schema_path=schema_path,
        classifier_command_parts=["codex"],
        classifier_model=None,
        classifier_timeout_seconds=45,
        classifier_max_output_chars=8000,
        effective_local_timezone=ZoneInfo("UTC"),
    )


async def test_heuristic_classifier_marks_completed_on_zero_exit() -> None:
    settings = HeuristicClassifierSettings(
        prompt_delivery_timeout_seconds=20,
        stuck_idle_timeout_seconds=900,
        effective_local_timezone=ZoneInfo("UTC"),
    )
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
    settings = HeuristicClassifierSettings(
        prompt_delivery_timeout_seconds=20,
        stuck_idle_timeout_seconds=900,
        effective_local_timezone=ZoneInfo("UTC"),
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


def test_codex_classifier_extracts_marked_json_from_terminal_output(tmp_path: Path) -> None:
    settings = make_codex_settings(tmp_path)
    classifier = CodexCliSessionClassifier(settings, ProviderManager())
    output = (
        "\x1b[31mnoise\x1b[0m\n"
        "__AILM_CLASSIFICATION_START__\n"
        "{\"state\":\"completed\",\"confidence\":0.99,\"reason\":\"done\","
        "\"suggested_action\":\"mark_completed\",\"provider_ready\":true,"
        "\"prompt_accepted\":true,\"recovery_action\":\"none\",\"retry_at\":null}\n"
        "__AILM_CLASSIFICATION_END__\n"
    )

    payload = classifier._extract_payload(output)

    assert payload.startswith("{\"state\":\"completed\"")


@pytest.mark.asyncio
async def test_codex_classifier_returns_after_marked_payload_without_waiting_for_process_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeStream:
        def __init__(self, chunks: list[str]) -> None:
            self._chunks = [chunk.encode("utf-8") for chunk in chunks]

        async def read(self, _size: int) -> bytes:
            await asyncio.sleep(0)
            if not self._chunks:
                return b""
            return self._chunks.pop(0)

    class FakeProcess:
        def __init__(self) -> None:
            self.pid = 4321
            self.returncode: int | None = None
            self.terminated = False
            self.stdout = FakeStream(
                [
                    "noise before output\n",
                    "__AILM_CLASSIFICATION_START__\n",
                    "{\"state\":\"ready_for_prompt\",\"confidence\":0.99,"
                    "\"reason\":\"ready\",\"suggested_action\":\"send_prompt\","
                    "\"provider_ready\":true,\"prompt_accepted\":false,"
                    "\"recovery_action\":\"none\",\"retry_at\":null}\n",
                    "__AILM_CLASSIFICATION_END__\n",
                ]
            )

        async def wait(self) -> int:
            while not self.terminated:
                await asyncio.sleep(0)
            self.returncode = -15
            return self.returncode

    process = FakeProcess()

    async def fake_create_subprocess_exec(*args, **kwargs):
        assert kwargs["start_new_session"] is True
        return process

    def fake_killpg(pid: int, sig: int) -> None:
        assert pid == process.pid
        process.terminated = True

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(os, "killpg", fake_killpg)

    settings = make_codex_settings(tmp_path)
    classifier = CodexCliSessionClassifier(settings, ProviderManager())
    job = JobRecord(
        job_id="job-stream",
        provider=JobProvider.CLAUDE,
        prompt="Inspect this session",
        active_prompt="Inspect this session",
        priority=50,
        retry_policy=RetryPolicy(),
        state=JobState.WAITING_FOR_PROVIDER_READY,
    )
    snapshot = SessionSnapshot(
        observed_at=utcnow(),
        tmux_target="ai-launcher-manager:job-stream",
        recent_output="Claude welcome screen",
    )

    result = await classifier.classify(job, snapshot)

    assert result.state == ClassificationState.READY_FOR_PROMPT
    assert process.terminated is True


@pytest.mark.asyncio
async def test_composite_classifier_crashes_when_primary_classifier_errors(tmp_path: Path) -> None:
    class ExplodingPrimary:
        async def classify(self, job: JobRecord, snapshot: SessionSnapshot) -> ClassificationResult:
            raise RuntimeError("classifier transport broke")

    heuristic_settings = HeuristicClassifierSettings(
        prompt_delivery_timeout_seconds=20,
        stuck_idle_timeout_seconds=900,
        effective_local_timezone=ZoneInfo("UTC"),
    )
    fallback = HeuristicSessionClassifier(heuristic_settings, ProviderManager())
    classifier = CompositeSessionClassifier(
        settings=CompositeClassifierSettings(
            classifier_enabled=True,
            classifier_min_confidence=0.65,
        ),
        primary=ExplodingPrimary(),  # type: ignore[arg-type]
        fallback=fallback,
    )
    job = JobRecord(
        job_id="job-3",
        provider=JobProvider.CODEX,
        prompt="echo hi",
        active_prompt="echo hi",
        priority=50,
        retry_policy=RetryPolicy(),
        state=JobState.RUNNING,
    )
    snapshot = SessionSnapshot(
        observed_at=utcnow(),
        tmux_target="ai-launcher-manager:job-3",
        recent_output="idle",
    )

    with pytest.raises(SessionClassificationError, match="unexpected classifier error: classifier transport broke"):
        await classifier.classify(job, snapshot)


@pytest.mark.asyncio
async def test_composite_classifier_crashes_on_low_confidence_codex_result(tmp_path: Path) -> None:
    class LowConfidencePrimary:
        async def classify(self, job: JobRecord, snapshot: SessionSnapshot) -> ClassificationResult:
            return ClassificationResult(
                state=ClassificationState.RUNNING,
                confidence=0.2,
                reason="ambiguous output",
                suggested_action=SuggestedAction.CONTINUE_MONITORING,
                provider_ready=True,
                prompt_accepted=True,
            )

    heuristic_settings = HeuristicClassifierSettings(
        prompt_delivery_timeout_seconds=20,
        stuck_idle_timeout_seconds=900,
        effective_local_timezone=ZoneInfo("UTC"),
    )
    fallback = HeuristicSessionClassifier(heuristic_settings, ProviderManager())
    classifier = CompositeSessionClassifier(
        settings=CompositeClassifierSettings(
            classifier_enabled=True,
            classifier_min_confidence=0.65,
        ),
        primary=LowConfidencePrimary(),  # type: ignore[arg-type]
        fallback=fallback,
    )
    job = JobRecord(
        job_id="job-4",
        provider=JobProvider.CODEX,
        prompt="echo hi",
        active_prompt="echo hi",
        priority=50,
        retry_policy=RetryPolicy(),
        state=JobState.RUNNING,
    )
    snapshot = SessionSnapshot(
        observed_at=utcnow(),
        tmux_target="ai-launcher-manager:job-4",
        recent_output="idle",
    )

    with pytest.raises(SessionClassificationError, match="confidence 0.20 is below the required 0.65"):
        await classifier.classify(job, snapshot)
