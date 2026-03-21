from __future__ import annotations

import asyncio
import re
from pathlib import Path

from app.core.config import Settings
from app.models.jobs import JobRecord, SessionSnapshot, utcnow
from app.utils.logging import get_logger


class TmuxManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger = get_logger("ai_launcher_manager.tmux")

    @property
    def session_name(self) -> str:
        return self.settings.tmux_session_name

    @property
    def wrapper_script(self) -> Path:
        return self.settings.app_dir / "scripts" / "run_managed_job.sh"

    def window_name_for_job(self, job_id: str) -> str:
        return f"job-{job_id}"

    async def _run(self, *args: str, check: bool = True, timeout: int = 15) -> tuple[int, str, str]:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError(f"Command timed out: {' '.join(args)}") from None

        stdout_text = stdout.decode().strip()
        stderr_text = stderr.decode().strip()
        if check and process.returncode != 0:
            raise RuntimeError(stderr_text or stdout_text or f"Command failed: {' '.join(args)}")
        return process.returncode, stdout_text, stderr_text

    async def session_exists(self) -> bool:
        code, _, _ = await self._run("tmux", "has-session", "-t", self.session_name, check=False)
        return code == 0

    async def ensure_session(self) -> None:
        if not await self.session_exists():
            await self._run("tmux", "new-session", "-d", "-s", self.session_name, "-n", "bootstrap")
        await self._run("tmux", "set-window-option", "-g", "remain-on-exit", "on")
        await self._run("tmux", "set-window-option", "-g", "allow-rename", "off")

    async def window_exists(self, window_name: str) -> bool:
        if not await self.session_exists():
            return False
        code, stdout, _ = await self._run(
            "tmux",
            "list-windows",
            "-t",
            self.session_name,
            "-F",
            "#{window_name}",
            check=False,
        )
        if code != 0:
            return False
        return window_name in set(filter(None, stdout.splitlines()))

    async def kill_window(self, window_name: str) -> None:
        await self._run(
            "tmux",
            "kill-window",
            "-t",
            f"{self.session_name}:{window_name}",
            check=False,
        )

    async def launch_job(self, job: JobRecord) -> tuple[str, str]:
        await self.ensure_session()
        window_name = self.window_name_for_job(job.job_id)
        if await self.window_exists(window_name):
            await self.kill_window(window_name)

        await self._run(
            "tmux",
            "new-window",
            "-d",
            "-t",
            self.session_name,
            "-n",
            window_name,
            "env",
            f"AILM_JOB_ID={job.job_id}",
            f"AILM_PROVIDER={job.provider.value}",
            f"AILM_JOB_COMMAND={job.command}",
            "bash",
            str(self.wrapper_script),
        )
        return self.session_name, window_name

    async def capture_snapshot(self, job: JobRecord) -> SessionSnapshot | None:
        if not job.tmux_window or not await self.window_exists(job.tmux_window):
            return None

        target = f"{self.session_name}:{job.tmux_window}"
        _, pane_info, _ = await self._run(
            "tmux",
            "list-panes",
            "-t",
            target,
            "-F",
            "#{pane_dead}|#{pane_pid}|#{pane_current_command}|#{pane_dead_status}",
        )
        pane_dead = False
        pane_pid: int | None = None
        pane_current_command: str | None = None
        exit_code: int | None = None
        if pane_info:
            parts = pane_info.split("|")
            pane_dead = parts[0] == "1"
            pane_pid = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
            pane_current_command = parts[2] if len(parts) > 2 else None
            if len(parts) > 3 and parts[3].lstrip("-").isdigit():
                exit_code = int(parts[3])

        _, output, _ = await self._run(
            "tmux",
            "capture-pane",
            "-p",
            "-t",
            target,
            "-S",
            f"-{self.settings.tmux_history_lines}",
        )
        sentinel_match = re.findall(r"__AILM_EXIT_CODE__=(\d+)", output)
        if sentinel_match:
            exit_code = int(sentinel_match[-1])

        return SessionSnapshot(
            observed_at=utcnow(),
            tmux_target=target,
            pane_dead=pane_dead,
            exit_code=exit_code,
            pane_pid=pane_pid,
            pane_current_command=pane_current_command,
            recent_output=output,
        )

    async def terminate_job(self, job: JobRecord) -> None:
        if not job.tmux_window or not await self.window_exists(job.tmux_window):
            return
        target = f"{self.session_name}:{job.tmux_window}"
        await self._run("tmux", "send-keys", "-t", target, "C-c", check=False)
        await asyncio.sleep(1)
        await self.kill_window(job.tmux_window)

    async def cleanup_job(self, job: JobRecord, *, force: bool = False) -> None:
        if force or self.settings.tmux_cleanup_on_terminal_state:
            await self.kill_window(job.tmux_window or self.window_name_for_job(job.job_id))

    async def discover_managed_windows(self) -> set[str]:
        if not await self.session_exists():
            return set()
        _, stdout, _ = await self._run(
            "tmux",
            "list-windows",
            "-t",
            self.session_name,
            "-F",
            "#{window_name}",
        )
        return {
            line.strip()
            for line in stdout.splitlines()
            if line.strip().startswith("job-")
        }
