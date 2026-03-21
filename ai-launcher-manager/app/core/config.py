from __future__ import annotations

import shlex
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AILM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI Launcher Manager"
    redis_url: str = "redis://localhost:6379/0"
    queue_namespace: str = "ailm"
    scheduler_poll_interval_seconds: int = Field(default=3, ge=1, le=300)
    monitor_poll_interval_seconds: int = Field(default=5, ge=1, le=300)
    enable_background_worker: bool = True
    worker_id: str = "worker-1"
    worker_execution_target: str = "container"

    tmux_session_name: str = "ai-launcher-manager"
    tmux_history_lines: int = Field(default=200, ge=50, le=5000)
    tmux_cleanup_on_terminal_state: bool = True

    classifier_enabled: bool = True
    classifier_command: str = "codex"
    classifier_model: str | None = None
    classifier_timeout_seconds: int = Field(default=600, ge=5, le=600)
    classifier_min_interval_seconds: int = Field(default=30, ge=1, le=3600)
    classifier_max_interval_seconds: int = Field(default=300, ge=1, le=86_400)
    classifier_min_confidence: float = Field(default=0.65, ge=0.0, le=1.0)
    classifier_max_output_chars: int = Field(default=8000, ge=500, le=64_000)
    stuck_idle_timeout_seconds: int = Field(default=900, ge=30, le=86_400)
    prompt_delivery_timeout_seconds: int = Field(default=20, ge=5, le=600)
    max_prompt_delivery_attempts: int = Field(default=3, ge=1, le=20)

    initial_concurrency_per_provider: int = Field(default=3, ge=1, le=100)
    initial_codex_concurrency: int | None = Field(default=None, ge=1, le=100)
    min_concurrency_per_provider: int = Field(default=1, ge=1, le=100)
    concurrency_safety_ceiling: int = Field(default=50, ge=1, le=100)
    concurrency_increase_after_successes: int = Field(default=3, ge=1, le=50)
    high_water_mark_reset_seconds: int = Field(default=3600, ge=60, le=86_400)

    local_timezone: str | None = None

    log_level: str = "INFO"
    test_mode: bool = False

    @property
    def app_dir(self) -> Path:
        return Path(__file__).resolve().parents[1]

    @property
    def classifier_prompt_path(self) -> Path:
        return self.app_dir / "prompts" / "session_state_classifier_prompt.md"

    @property
    def classifier_schema_path(self) -> Path:
        return self.app_dir / "prompts" / "session_state_classifier_schema.json"

    @property
    def classifier_command_parts(self) -> list[str]:
        return shlex.split(self.classifier_command)

    @property
    def worker_heartbeat_ttl_seconds(self) -> int:
        return max(self.scheduler_poll_interval_seconds, self.monitor_poll_interval_seconds) * 4

    @property
    def effective_local_timezone(self) -> ZoneInfo:
        if self.local_timezone:
            try:
                return ZoneInfo(self.local_timezone)
            except ZoneInfoNotFoundError as exc:  # pragma: no cover - guarded by config
                raise ValueError(f"Unknown timezone configured: {self.local_timezone}") from exc

        detected = datetime.now().astimezone().tzinfo
        if isinstance(detected, ZoneInfo):
            return detected
        return ZoneInfo("UTC")
