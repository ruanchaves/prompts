from __future__ import annotations

from app.models.jobs import JobProvider
from app.services.provider_manager import ProviderManager


def test_provider_manager_uses_fixed_launch_commands() -> None:
    manager = ProviderManager()

    assert manager.launch_command_display(JobProvider.CODEX) == "codex --yolo"
    assert manager.launch_command_display(JobProvider.CLAUDE) == "claude --dangerously-skip-permissions"
    assert "rate limited" in manager.CONTINUE_MESSAGE.lower()
