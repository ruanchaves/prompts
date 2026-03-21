from __future__ import annotations

from app.models.jobs import JobProvider, JobRecord, RecoveryAction


class ProviderManager:
    CONTINUE_MESSAGE = "Continue where you left off. The previous attempt was rate limited."

    def launch_command_args(self, provider: JobProvider) -> list[str]:
        if provider == JobProvider.CODEX:
            return ["codex", "--yolo"]
        return ["claude", "--dangerously-skip-permissions"]

    def launch_command_display(self, provider: JobProvider) -> str:
        return " ".join(self.launch_command_args(provider))

    def default_prompt_for_job(self, job: JobRecord) -> str:
        return job.prompt

    def continue_message_for_job(self, job: JobRecord) -> str:
        return self.CONTINUE_MESSAGE

    def default_recovery_action(self, provider: JobProvider) -> RecoveryAction:
        if provider == JobProvider.CLAUDE:
            return RecoveryAction.PRESS_CONTINUE
        return RecoveryAction.RELAUNCH_PROVIDER
