from __future__ import annotations

import argparse
import asyncio
import os
import signal
from collections.abc import Iterable
from pathlib import Path

from app.core.config import Settings
from app.main import build_services
from app.utils.logging import configure_logging, get_logger


def load_env_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Env file not found: {path}")

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid env file line: {raw_line}")
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip()


def _register_signal_handlers(stop_event: asyncio.Event, signals_to_handle: Iterable[signal.Signals]) -> None:
    loop = asyncio.get_running_loop()
    for sig in signals_to_handle:
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:  # pragma: no cover - platform-specific
            signal.signal(sig, lambda *_args: stop_event.set())


async def run_host_worker(env_file: Path | None = None) -> None:
    if env_file is not None:
        load_env_file(env_file)

    settings = Settings(
        enable_background_worker=True,
        worker_execution_target="host",
    )
    configure_logging(settings.log_level)
    logger = get_logger("ai_launcher_manager.host_worker")
    services = build_services(settings)
    stop_event = asyncio.Event()
    _register_signal_handlers(stop_event, (signal.SIGINT, signal.SIGTERM))

    logger.info(
        "Starting host worker %s against %s using tmux session %s",
        settings.worker_id,
        settings.redis_url,
        settings.tmux_session_name,
    )

    await services.worker.start()
    stop_task = asyncio.create_task(stop_event.wait(), name="host-worker-stop")
    failure_task = asyncio.create_task(services.worker.wait_for_failure(), name="host-worker-failure")
    try:
        done, pending = await asyncio.wait(
            {stop_task, failure_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()

        if failure_task in done:
            try:
                await failure_task
            except Exception as exc:
                logger.critical("Host worker crashed because a background task failed", exc_info=exc)
                raise RuntimeError(f"Host worker crashed: {exc}") from exc
    finally:
        await asyncio.gather(stop_task, failure_task, return_exceptions=True)
        logger.info("Stopping host worker %s", settings.worker_id)
        await services.worker.stop()
        await services.redis.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the AI Launcher Manager worker on the host.")
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Optional env file to load before constructing settings.",
    )
    args = parser.parse_args()
    asyncio.run(run_host_worker(args.env_file))


if __name__ == "__main__":
    main()
