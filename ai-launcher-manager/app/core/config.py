from __future__ import annotations

import shlex
from pathlib import Path

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
    max_concurrent_jobs: int = Field(default=2, ge=1, le=100)
    scheduler_poll_interval_seconds: int = Field(default=3, ge=1, le=300)
    monitor_poll_interval_seconds: int = Field(default=5, ge=1, le=300)
    enable_background_worker: bool = True
    worker_id: str = "worker-1"

    tmux_session_name: str = "ai-launcher-manager"
    tmux_history_lines: int = Field(default=200, ge=50, le=5000)
    tmux_cleanup_on_terminal_state: bool = False

    classifier_enabled: bool = True
    classifier_command: str = "codex"
    classifier_model: str | None = None
    classifier_timeout_seconds: int = Field(default=45, ge=5, le=600)
    classifier_min_interval_seconds: int = Field(default=30, ge=1, le=3600)
    classifier_max_interval_seconds: int = Field(default=300, ge=1, le=86_400)
    classifier_min_confidence: float = Field(default=0.65, ge=0.0, le=1.0)
    classifier_max_output_chars: int = Field(default=8000, ge=500, le=64_000)
    stuck_idle_timeout_seconds: int = Field(default=900, ge=30, le=86_400)

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
