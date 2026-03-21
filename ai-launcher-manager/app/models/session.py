from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.common import utcnow


class SessionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_at: datetime = Field(default_factory=utcnow)
    tmux_target: str
    pane_dead: bool = False
    exit_code: int | None = None
    pane_pid: int | None = None
    pane_current_command: str | None = None
    recent_output: str = ""
