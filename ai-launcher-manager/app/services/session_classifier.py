from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import signal
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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


class SessionClassificationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class HeuristicClassifierSettings:
    prompt_delivery_timeout_seconds: int
    stuck_idle_timeout_seconds: int
    effective_local_timezone: ZoneInfo


@dataclass(frozen=True, slots=True)
class CodexClassifierSettings:
    classifier_prompt_path: Path
    classifier_schema_path: Path
    classifier_command_parts: list[str]
    classifier_model: str | None
    classifier_timeout_seconds: int
    classifier_max_output_chars: int
    effective_local_timezone: ZoneInfo


@dataclass(frozen=True, slots=True)
class CompositeClassifierSettings:
    classifier_enabled: bool
    classifier_min_confidence: float


class HeuristicSessionClassifier:
    RATE_LIMIT_PATTERNS = (
        "rate limit reached",
        "rate limited",
        "usage limit reached",
        "out of extra usage",
        "try again in",
        "limit reached",
        "hit your limit",
        "please try again in",
    )

    # Lines containing these substrings are informational banners, not
    # provider state signals.  They must be stripped before pattern matching
    # to avoid false positives (e.g. Codex's "New 2x rate limits until
    # April 2nd" tip being classified as a rate-limit event).
    BANNER_NOISE_PATTERNS = (
        "tip:",
        "2x rate limits",
        "/model to change",
        "/fast to enable",
        "/skills to list",
        "/init to create",
        "/experimental",
    )

    READY_PATTERNS = (
        "what would you like me to do",
        "how can i help",
        "send a message",
        "welcome to codex",
        "welcome to claude",
    )

    def __init__(self, settings: HeuristicClassifierSettings, provider_manager: ProviderManager) -> None:
        self.settings = settings
        self.provider_manager = provider_manager

    @classmethod
    def _strip_banner_lines(cls, text: str) -> str:
        lines = text.splitlines()
        return "\n".join(
            line for line in lines
            if not any(noise in line for noise in cls.BANNER_NOISE_PATTERNS)
        )

    async def classify(self, job: JobRecord, snapshot: SessionSnapshot) -> ClassificationResult:
        output = self._strip_banner_lines(snapshot.recent_output.lower())

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
                prompt_accepted = job.provider == JobProvider.CLAUDE
                return ClassificationResult(
                    state=ClassificationState.RUNNING,
                    confidence=0.68,
                    reason="session output changed after prompt injection",
                    suggested_action=SuggestedAction.CONTINUE_MONITORING,
                    provider_ready=True,
                    prompt_accepted=prompt_accepted,
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
    ANSI_ESCAPE_RE = re.compile(
        r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1B\\))"
    )
    MARKER_START = "__AILM_CLASSIFICATION_START__"
    MARKER_END = "__AILM_CLASSIFICATION_END__"

    def __init__(self, settings: CodexClassifierSettings, provider_manager: ProviderManager) -> None:
        self.settings = settings
        self.provider_manager = provider_manager
        self.logger = get_logger("ai_launcher_manager.codex_classifier")
        self.prompt_template = self.settings.classifier_prompt_path.read_text(encoding="utf-8")
        self.schema_text = self.settings.classifier_schema_path.read_text(encoding="utf-8")

    def _build_prompt(self, job: JobRecord, snapshot: SessionSnapshot) -> str:
        def _preview_text(value: str | None, *, limit: int = 1500) -> str | None:
            if value is None:
                return None
            if len(value) <= limit:
                return value
            return f"{value[:limit]}\n...<truncated {len(value) - limit} chars>"

        local_now = datetime.now(self.settings.effective_local_timezone)
        context = {
            "job_id": job.job_id,
            "provider": job.provider.value,
            "job_state": job.state.value,
            "attempt_count": job.attempt_count,
            "prompt_attempt_count": job.prompt_attempt_count,
            "launch_command": job.launch_command,
            "original_prompt": _preview_text(job.prompt),
            "pending_prompt": _preview_text(job.active_prompt),
            "original_prompt_chars": len(job.prompt),
            "pending_prompt_chars": len(job.active_prompt) if job.active_prompt is not None else 0,
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
        return self.prompt_template.format(
            context=json.dumps(context, indent=2),
            schema=self.schema_text,
            marker_start=self.MARKER_START,
            marker_end=self.MARKER_END,
        )

    def _build_command(self, prompt_path: Path) -> list[str]:
        command_parts = [*self.settings.classifier_command_parts]
        if self.settings.classifier_model:
            command_parts.extend(["-m", self.settings.classifier_model])
        command_parts.append("--yolo")
        classifier_command = " ".join(
            shlex.quote(part) for part in command_parts
        )
        shell_command = f'{classifier_command} "$(cat {shlex.quote(str(prompt_path))})"'
        return ["script", "-qefc", shell_command, "/dev/null"]

    @classmethod
    def _sanitize_output(cls, output: str) -> str:
        sanitized = output.replace("\r", "\n")
        sanitized = cls.ANSI_ESCAPE_RE.sub("", sanitized)
        sanitized = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", sanitized)
        return sanitized

    @classmethod
    def _search_payload(cls, output: str) -> str | None:
        sanitized = cls._sanitize_output(output)
        pattern = re.compile(
            rf"{re.escape(cls.MARKER_START)}\s*(\{{.*?\}})\s*{re.escape(cls.MARKER_END)}",
            re.DOTALL,
        )
        match = pattern.search(sanitized)
        if not match:
            return None
        return match.group(1)

    @classmethod
    def _extract_payload(cls, output: str) -> str:
        match_payload = cls._search_payload(output)
        if match_payload is not None:
            return match_payload
        sanitized = cls._sanitize_output(output)
        excerpt = sanitized[-2000:].strip() or "<no output captured>"
        raise SessionClassificationError(
            "codex classifier did not return the required JSON markers. "
            f"Captured output excerpt:\n{excerpt}"
        )

    @staticmethod
    def _failure_message(job: JobRecord, snapshot: SessionSnapshot, detail: str) -> str:
        return (
            "codex session classification failed "
            f"for job {job.job_id} ({snapshot.tmux_target}): {detail}"
        )

    async def _terminate_process(self, process: asyncio.subprocess.Process, *, force: bool = False) -> None:
        if process.returncode is not None:
            return

        sig = signal.SIGKILL if force else signal.SIGTERM
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            return
        except PermissionError:
            if force:
                process.kill()

    async def _wait_for_exit(self, process: asyncio.subprocess.Process, *, timeout: int = 5) -> None:
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            await self._terminate_process(process, force=True)
            await process.wait()

    async def _read_payload(
        self,
        process: asyncio.subprocess.Process,
        job: JobRecord,
        snapshot: SessionSnapshot,
    ) -> str:
        assert process.stdout is not None
        output = ""

        while True:
            chunk = await process.stdout.read(4096)
            if not chunk:
                break

            output += chunk.decode("utf-8", errors="replace")
            payload = self._search_payload(output)
            if payload is not None:
                await self._terminate_process(process)
                await self._wait_for_exit(process)
                return payload

        if process.returncode is None:
            await process.wait()

        if process.returncode != 0:
            detail = output.strip() or f"classifier command exited with status {process.returncode}"
            raise SessionClassificationError(self._failure_message(job, snapshot, detail))

        try:
            return self._extract_payload(output)
        except SessionClassificationError as exc:
            raise SessionClassificationError(self._failure_message(job, snapshot, str(exc))) from exc

    async def classify(self, job: JobRecord, snapshot: SessionSnapshot) -> ClassificationResult:
        prompt = self._build_prompt(job, snapshot)
        with tempfile.TemporaryDirectory(prefix="ailm-classifier-") as temp_dir:
            prompt_path = Path(temp_dir) / "classification_prompt.txt"
            prompt_path.write_text(prompt, encoding="utf-8")
            command = self._build_command(prompt_path)

            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                payload = await asyncio.wait_for(
                    self._read_payload(process, job, snapshot),
                    timeout=self.settings.classifier_timeout_seconds,
                )
            except asyncio.TimeoutError:
                await self._terminate_process(process, force=True)
                await process.wait()
                raise SessionClassificationError(
                    self._failure_message(
                        job,
                        snapshot,
                        f"classifier command timed out after {self.settings.classifier_timeout_seconds} seconds",
                    )
                ) from None

            try:
                result = ClassificationResult.model_validate_json(payload)
            except Exception as exc:
                raise SessionClassificationError(
                    self._failure_message(job, snapshot, f"invalid classifier JSON payload: {exc}")
                ) from exc
            result.source = "codex"
            return result


class CompositeSessionClassifier:
    def __init__(
        self,
        settings: CompositeClassifierSettings,
        primary: CodexCliSessionClassifier,
        fallback: HeuristicSessionClassifier,
    ) -> None:
        self.settings = settings
        self.primary = primary
        self.fallback = fallback
        self.logger = get_logger("ai_launcher_manager.classifier")

    async def classify(self, job: JobRecord, snapshot: SessionSnapshot) -> ClassificationResult:
        if not self.settings.classifier_enabled:
            return await self.fallback.classify(job, snapshot)

        try:
            codex_result = await self.primary.classify(job, snapshot)
        except SessionClassificationError:
            raise
        except Exception as exc:
            raise SessionClassificationError(
                "codex session classification failed "
                f"for job {job.job_id} ({snapshot.tmux_target}): unexpected classifier error: {exc}"
            ) from exc
        if codex_result.confidence < self.settings.classifier_min_confidence:
            raise SessionClassificationError(
                "codex session classification failed "
                f"for job {job.job_id} ({snapshot.tmux_target}): "
                f"classifier confidence {codex_result.confidence:.2f} is below the required "
                f"{self.settings.classifier_min_confidence:.2f}"
            )
        return codex_result
