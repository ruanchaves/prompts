from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Protocol

from app.core.config import Settings
from app.models.jobs import (
    ClassificationResult,
    ClassificationState,
    JobRecord,
    SessionSnapshot,
    SuggestedAction,
)
from app.utils.logging import get_logger


class SessionStateClassifier(Protocol):
    async def classify(self, job: JobRecord, snapshot: SessionSnapshot) -> ClassificationResult:
        ...


class HeuristicSessionClassifier:
    RATE_LIMIT_PATTERNS = (
        "rate limit",
        "too many requests",
        "quota exceeded",
        "try again later",
    )
    IDLE_PATTERNS = (
        "waiting for input",
        "press enter",
        "continue? [y/n]",
        "approve this command",
        "need your approval",
    )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def classify(self, job: JobRecord, snapshot: SessionSnapshot) -> ClassificationResult:
        output = snapshot.recent_output.lower()

        if snapshot.pane_dead and snapshot.exit_code == 0:
            return ClassificationResult(
                state=ClassificationState.COMPLETED,
                confidence=0.99,
                reason="tmux pane exited with code 0",
                suggested_action=SuggestedAction.MARK_COMPLETED,
                source="heuristic",
            )

        if snapshot.pane_dead and snapshot.exit_code not in (None, 0):
            return ClassificationResult(
                state=ClassificationState.FAILED,
                confidence=0.99,
                reason=f"tmux pane exited with non-zero status {snapshot.exit_code}",
                suggested_action=SuggestedAction.MARK_FAILED,
                source="heuristic",
            )

        if any(pattern in output for pattern in self.RATE_LIMIT_PATTERNS):
            return ClassificationResult(
                state=ClassificationState.RATE_LIMITED,
                confidence=0.91,
                reason="session output matches known rate-limit patterns",
                suggested_action=SuggestedAction.RETRY,
                source="heuristic",
            )

        if any(pattern in output for pattern in self.IDLE_PATTERNS):
            return ClassificationResult(
                state=ClassificationState.IDLE,
                confidence=0.76,
                reason="session output indicates it is waiting for human input",
                suggested_action=SuggestedAction.NEEDS_HUMAN,
                source="heuristic",
            )

        reference_time = job.last_output_at or job.started_at or job.updated_at
        inactivity_seconds = (snapshot.observed_at - reference_time).total_seconds()
        if inactivity_seconds >= self.settings.stuck_idle_timeout_seconds:
            return ClassificationResult(
                state=ClassificationState.STUCK,
                confidence=0.8,
                reason=f"no output change observed for {int(inactivity_seconds)} seconds",
                suggested_action=SuggestedAction.RETRY,
                source="heuristic",
            )

        if snapshot.recent_output.strip():
            return ClassificationResult(
                state=ClassificationState.RUNNING,
                confidence=0.6,
                reason="session still has live output and no terminal signal was detected",
                suggested_action=SuggestedAction.CONTINUE_MONITORING,
                source="heuristic",
            )

        return ClassificationResult(
            state=ClassificationState.IDLE,
            confidence=0.55,
            reason="session output is empty and no stronger signal is available",
            suggested_action=SuggestedAction.CONTINUE_MONITORING,
            source="heuristic",
        )


class CodexCliSessionClassifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger = get_logger("ai_launcher_manager.codex_classifier")
        self.prompt_template = self.settings.classifier_prompt_path.read_text(encoding="utf-8")

    def _build_prompt(self, job: JobRecord, snapshot: SessionSnapshot) -> str:
        context = {
            "job_id": job.job_id,
            "provider": job.provider.value,
            "attempt_count": job.attempt_count,
            "current_state": job.state.value,
            "command": job.command,
            "tmux_target": snapshot.tmux_target,
            "pane_dead": snapshot.pane_dead,
            "exit_code": snapshot.exit_code,
            "observed_at": snapshot.observed_at.isoformat(),
            "recent_output": snapshot.recent_output[-self.settings.classifier_max_output_chars :],
        }
        return self.prompt_template.format(context=json.dumps(context, indent=2))

    async def classify(self, job: JobRecord, snapshot: SessionSnapshot) -> ClassificationResult:
        prompt = self._build_prompt(job, snapshot)
        with tempfile.TemporaryDirectory(prefix="ailm-classifier-") as temp_dir:
            output_path = Path(temp_dir) / "classification.json"
            command = [
                *self.settings.classifier_command_parts,
                "exec",
                "--skip-git-repo-check",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--color",
                "never",
                "--output-schema",
                str(self.settings.classifier_schema_path),
                "-o",
                str(output_path),
            ]
            if self.settings.classifier_model:
                command.extend(["-m", self.settings.classifier_model])
            command.append("-")

            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(prompt.encode()),
                    timeout=self.settings.classifier_timeout_seconds,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise RuntimeError("codex classifier timed out") from None

            if process.returncode != 0:
                raise RuntimeError(stderr.decode().strip() or stdout.decode().strip() or "codex classifier failed")

            payload = output_path.read_text(encoding="utf-8").strip()
            result = ClassificationResult.model_validate(json.loads(payload))
            result.source = "codex"
            return result


class CompositeSessionClassifier:
    def __init__(
        self,
        settings: Settings,
        primary: CodexCliSessionClassifier,
        fallback: HeuristicSessionClassifier,
    ) -> None:
        self.settings = settings
        self.primary = primary
        self.fallback = fallback
        self.logger = get_logger("ai_launcher_manager.classifier")

    async def classify(self, job: JobRecord, snapshot: SessionSnapshot) -> ClassificationResult:
        heuristic_result = await self.fallback.classify(job, snapshot)
        if not self.settings.classifier_enabled:
            return heuristic_result

        try:
            codex_result = await self.primary.classify(job, snapshot)
        except Exception as exc:  # pragma: no cover - exercised via fallback path
            self.logger.warning("codex classification failed for job %s: %s", job.job_id, exc)
            heuristic_result.reason = f"codex classifier unavailable; {heuristic_result.reason}"
            heuristic_result.source = "combined"
            return heuristic_result

        if snapshot.pane_dead and heuristic_result.state in {ClassificationState.COMPLETED, ClassificationState.FAILED}:
            if codex_result.state != heuristic_result.state:
                heuristic_result.reason = (
                    f"codex suggested {codex_result.state.value}, but deterministic exit signals indicate "
                    f"{heuristic_result.state.value}"
                )
                heuristic_result.source = "combined"
                return heuristic_result

        if codex_result.confidence >= self.settings.classifier_min_confidence:
            return codex_result

        heuristic_result.reason = (
            f"codex confidence {codex_result.confidence:.2f} below threshold; {heuristic_result.reason}"
        )
        heuristic_result.source = "combined"
        return heuristic_result
