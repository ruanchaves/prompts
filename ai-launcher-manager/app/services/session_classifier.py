from __future__ import annotations

import asyncio
import json
import re
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import Settings
from app.models.jobs import (
    ClassificationResult,
    ClassificationState,
    JobState,
    JobProvider,
    JobRecord,
    RecoveryAction,
    SessionSnapshot,
    SuggestedAction,
)
from app.services.provider_manager import ProviderManager
from app.utils.logging import get_logger


class SessionStateClassifier(Protocol):
    async def classify(self, job: JobRecord, snapshot: SessionSnapshot) -> ClassificationResult:
        ...


class HeuristicSessionClassifier:
    RATE_LIMIT_PATTERNS = (
        "rate limit",
        "usage limit reached",
        "out of extra usage",
        "try again in",
        "limit reached",
        "hit your limit",
        "please try again in",
    )

    READY_PATTERNS = (
        "what would you like me to do",
        "how can i help",
        "send a message",
        "welcome to codex",
        "welcome to claude",
    )

    def __init__(self, settings: Settings, provider_manager: ProviderManager) -> None:
        self.settings = settings
        self.provider_manager = provider_manager

    async def classify(self, job: JobRecord, snapshot: SessionSnapshot) -> ClassificationResult:
        output = snapshot.recent_output.lower()

        if snapshot.pane_dead and snapshot.exit_code == 0:
            return ClassificationResult(
                state=ClassificationState.COMPLETED,
                confidence=0.99,
                reason="tmux pane exited with code 0",
                suggested_action=SuggestedAction.MARK_COMPLETED,
                provider_ready=job.provider_ready_at is not None,
                prompt_accepted=job.prompt_confirmed_at is not None,
                source="heuristic",
            )

        if snapshot.pane_dead and snapshot.exit_code not in (None, 0):
            return ClassificationResult(
                state=ClassificationState.FAILED,
                confidence=0.99,
                reason=f"tmux pane exited with non-zero status {snapshot.exit_code}",
                suggested_action=SuggestedAction.MARK_FAILED,
                provider_ready=job.provider_ready_at is not None,
                prompt_accepted=job.prompt_confirmed_at is not None,
                source="heuristic",
            )

        if any(pattern in output for pattern in self.RATE_LIMIT_PATTERNS):
            retry_at = self._parse_retry_at(output)
            return ClassificationResult(
                state=ClassificationState.RATE_LIMITED,
                confidence=0.88,
                reason="session output matches known rate-limit patterns",
                suggested_action=SuggestedAction.SCHEDULE_RETRY,
                provider_ready=True,
                prompt_accepted=job.prompt_confirmed_at is not None,
                recovery_action=self._default_rate_limit_recovery(job.provider),
                retry_at=retry_at,
                source="heuristic",
            )

        if job.state == JobState.WAITING_FOR_PROVIDER_READY:
            if any(pattern in output for pattern in self.READY_PATTERNS) or snapshot.recent_output.strip():
                return ClassificationResult(
                    state=ClassificationState.READY_FOR_PROMPT,
                    confidence=0.55,
                    reason="provider has produced output and may be ready for prompt delivery",
                    suggested_action=SuggestedAction.SEND_PROMPT,
                    provider_ready=True,
                    prompt_accepted=False,
                    source="heuristic",
                )
            return ClassificationResult(
                state=ClassificationState.WAITING_FOR_PROVIDER_READY,
                confidence=0.7,
                reason="provider is still starting and no readiness signal was detected",
                suggested_action=SuggestedAction.CONTINUE_MONITORING,
                provider_ready=False,
                prompt_accepted=False,
                source="heuristic",
            )

        if job.state == JobState.SENDING_PROMPT:
            if job.prompt_sent_at and job.last_output_at and job.last_output_at > job.prompt_sent_at:
                return ClassificationResult(
                    state=ClassificationState.RUNNING,
                    confidence=0.68,
                    reason="session output changed after prompt injection",
                    suggested_action=SuggestedAction.CONTINUE_MONITORING,
                    provider_ready=True,
                    prompt_accepted=True,
                    source="heuristic",
                )

            if job.prompt_sent_at and (
                snapshot.observed_at - job.prompt_sent_at
            ).total_seconds() >= self.settings.prompt_delivery_timeout_seconds:
                return ClassificationResult(
                    state=ClassificationState.PROMPT_DELIVERY_FAILED,
                    confidence=0.75,
                    reason="prompt delivery timeout elapsed without meaningful output",
                    suggested_action=SuggestedAction.RETRY_SEND_PROMPT,
                    provider_ready=True,
                    prompt_accepted=False,
                    source="heuristic",
                )

        reference_time = job.last_output_at or job.started_at or job.updated_at
        inactivity_seconds = (snapshot.observed_at - reference_time).total_seconds()
        if inactivity_seconds >= self.settings.stuck_idle_timeout_seconds:
            return ClassificationResult(
                state=ClassificationState.STUCK,
                confidence=0.8,
                reason=f"no output change observed for {int(inactivity_seconds)} seconds",
                suggested_action=SuggestedAction.SCHEDULE_RETRY,
                provider_ready=job.provider_ready_at is not None,
                prompt_accepted=job.prompt_confirmed_at is not None,
                recovery_action=RecoveryAction.RELAUNCH_PROVIDER,
                source="heuristic",
            )

        return ClassificationResult(
            state=ClassificationState.RUNNING,
            confidence=0.55,
            reason="session is still live and no stronger fallback signal is available",
            suggested_action=SuggestedAction.CONTINUE_MONITORING,
            provider_ready=job.provider_ready_at is not None or job.state != JobState.WAITING_FOR_PROVIDER_READY,
            prompt_accepted=job.prompt_confirmed_at is not None or job.state == JobState.RUNNING,
            source="heuristic",
        )

    def _default_rate_limit_recovery(self, provider: JobProvider) -> RecoveryAction:
        if provider == JobProvider.CLAUDE:
            return RecoveryAction.PRESS_CONTINUE
        return RecoveryAction.RELAUNCH_PROVIDER

    def _parse_retry_at(self, output: str) -> datetime | None:
        now_local = datetime.now(self.settings.effective_local_timezone)

        relative_match = re.search(r"try again in\s+(\d+)\s+hours?", output)
        if relative_match:
            hours = int(relative_match.group(1))
            return now_local + timedelta(hours=hours)

        time_match = re.search(
            r"resets?(?:\s+at)?\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?(?:\s*\(([^)]+)\))?",
            output,
        )
        if not time_match:
            return None

        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        ampm = (time_match.group(3) or "").lower()
        timezone_name = time_match.group(4)

        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0

        source_zone = self.settings.effective_local_timezone
        if timezone_name:
            try:
                source_zone = ZoneInfo(timezone_name)
            except ZoneInfoNotFoundError:
                if timezone_name.upper() == "UTC":
                    source_zone = ZoneInfo("UTC")

        source_now = now_local.astimezone(source_zone)
        retry_at = source_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if retry_at <= source_now:
            retry_at += timedelta(days=1)
        return retry_at.astimezone(self.settings.effective_local_timezone)


class CodexCliSessionClassifier:
    def __init__(self, settings: Settings, provider_manager: ProviderManager) -> None:
        self.settings = settings
        self.provider_manager = provider_manager
        self.logger = get_logger("ai_launcher_manager.codex_classifier")
        self.prompt_template = self.settings.classifier_prompt_path.read_text(encoding="utf-8")

    def _build_prompt(self, job: JobRecord, snapshot: SessionSnapshot) -> str:
        local_now = datetime.now(self.settings.effective_local_timezone)
        context = {
            "job_id": job.job_id,
            "provider": job.provider.value,
            "job_state": job.state.value,
            "attempt_count": job.attempt_count,
            "prompt_attempt_count": job.prompt_attempt_count,
            "launch_command": job.launch_command,
            "original_prompt": job.prompt,
            "pending_prompt": job.active_prompt,
            "continue_message": self.provider_manager.continue_message_for_job(job),
            "provider_ready_at": job.provider_ready_at.isoformat() if job.provider_ready_at else None,
            "prompt_sent_at": job.prompt_sent_at.isoformat() if job.prompt_sent_at else None,
            "prompt_confirmed_at": job.prompt_confirmed_at.isoformat() if job.prompt_confirmed_at else None,
            "last_rate_limit_at": job.last_rate_limit_at.isoformat() if job.last_rate_limit_at else None,
            "recovery_action": job.recovery_action.value,
            "current_local_time": local_now.isoformat(),
            "local_timezone": str(self.settings.effective_local_timezone),
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
                    process.communicate(prompt.encode("utf-8")),
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
