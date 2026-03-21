from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import os
import signal

from fastapi import FastAPI
from redis.asyncio import Redis, from_url

from app.api.routes.health import router as health_router
from app.api.routes.jobs import router as jobs_router
from app.core.config import Settings
from app.models.jobs import JobProvider
from app.services.concurrency_controller import ConcurrencyController, ConcurrencySettings
from app.services.provider_manager import ProviderManager
from app.services.redis_queue import RedisQueue, RedisQueueSettings
from app.services.recovery import RecoveryService
from app.services.session_classifier import (
    CodexCliSessionClassifier,
    CodexClassifierSettings,
    CompositeClassifierSettings,
    CompositeSessionClassifier,
    HeuristicClassifierSettings,
    HeuristicSessionClassifier,
)
from app.services.session_monitor import MonitorSettings, SessionMonitor
from app.services.tmux_manager import TmuxManager, TmuxSettings
from app.services.worker import WorkerService, WorkerSettings
from app.utils.logging import configure_logging, get_logger


@dataclass(slots=True)
class AppServices:
    settings: Settings
    redis: Redis
    queue: RedisQueue
    provider_manager: ProviderManager
    concurrency_controller: ConcurrencyController
    tmux_manager: TmuxManager
    classifier: CompositeSessionClassifier
    session_monitor: SessionMonitor
    recovery: RecoveryService
    worker: WorkerService


def _crash_process_on_worker_failure(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return

    exc = task.exception()
    if exc is None:
        return

    logger = get_logger("ai_launcher_manager.app")
    logger.critical("Embedded background worker crashed; terminating process", exc_info=exc)
    try:
        os.kill(os.getpid(), signal.SIGTERM)
    except AttributeError:  # pragma: no cover - platform-specific
        raise SystemExit(1) from exc


def build_services(settings: Settings, redis_client: Redis | None = None) -> AppServices:
    redis = redis_client or from_url(settings.redis_url, decode_responses=True)

    queue_settings = RedisQueueSettings(
        queue_namespace=settings.queue_namespace,
        worker_heartbeat_ttl_seconds=settings.worker_heartbeat_ttl_seconds,
    )
    queue = RedisQueue(redis, queue_settings)

    provider_manager = ProviderManager()
    initial_concurrency_overrides: dict[JobProvider, int] = {}
    if settings.initial_codex_concurrency is not None:
        initial_concurrency_overrides[JobProvider.CODEX] = settings.initial_codex_concurrency

    concurrency_settings = ConcurrencySettings(
        queue_namespace=settings.queue_namespace,
        initial_concurrency_per_provider=settings.initial_concurrency_per_provider,
        initial_concurrency_overrides=initial_concurrency_overrides,
        min_concurrency_per_provider=settings.min_concurrency_per_provider,
        concurrency_safety_ceiling=settings.concurrency_safety_ceiling,
        concurrency_increase_after_successes=settings.concurrency_increase_after_successes,
        high_water_mark_reset_seconds=settings.high_water_mark_reset_seconds,
    )
    concurrency_controller = ConcurrencyController(redis, concurrency_settings)

    tmux_settings = TmuxSettings(
        tmux_session_name=settings.tmux_session_name,
        tmux_history_lines=settings.tmux_history_lines,
        tmux_cleanup_on_terminal_state=settings.tmux_cleanup_on_terminal_state,
        app_dir=settings.app_dir,
    )
    tmux_manager = TmuxManager(tmux_settings)

    effective_tz = settings.effective_local_timezone

    heuristic_settings = HeuristicClassifierSettings(
        prompt_delivery_timeout_seconds=settings.prompt_delivery_timeout_seconds,
        stuck_idle_timeout_seconds=settings.stuck_idle_timeout_seconds,
        effective_local_timezone=effective_tz,
    )
    codex_settings = CodexClassifierSettings(
        classifier_prompt_path=settings.classifier_prompt_path,
        classifier_schema_path=settings.classifier_schema_path,
        classifier_command_parts=settings.classifier_command_parts,
        classifier_model=settings.classifier_model,
        classifier_timeout_seconds=settings.classifier_timeout_seconds,
        classifier_max_output_chars=settings.classifier_max_output_chars,
        effective_local_timezone=effective_tz,
    )
    composite_settings = CompositeClassifierSettings(
        classifier_enabled=settings.classifier_enabled,
        classifier_min_confidence=settings.classifier_min_confidence,
    )

    classifier = CompositeSessionClassifier(
        settings=composite_settings,
        primary=CodexCliSessionClassifier(codex_settings, provider_manager),
        fallback=HeuristicSessionClassifier(heuristic_settings, provider_manager),
    )

    monitor_settings = MonitorSettings(
        classifier_max_output_chars=settings.classifier_max_output_chars,
        classifier_min_interval_seconds=settings.classifier_min_interval_seconds,
        classifier_max_interval_seconds=settings.classifier_max_interval_seconds,
        prompt_delivery_timeout_seconds=settings.prompt_delivery_timeout_seconds,
        max_prompt_delivery_attempts=settings.max_prompt_delivery_attempts,
    )
    session_monitor = SessionMonitor(
        settings=monitor_settings,
        queue=queue,
        tmux_manager=tmux_manager,
        classifier=classifier,
        provider_manager=provider_manager,
        concurrency_controller=concurrency_controller,
    )

    recovery = RecoveryService(queue, tmux_manager, provider_manager)

    worker_settings = WorkerSettings(
        scheduler_poll_interval_seconds=settings.scheduler_poll_interval_seconds,
        monitor_poll_interval_seconds=settings.monitor_poll_interval_seconds,
        worker_id=settings.worker_id,
        worker_execution_target=settings.worker_execution_target,
        tmux_session_name=settings.tmux_session_name,
    )
    worker = WorkerService(
        worker_settings,
        queue,
        tmux_manager,
        session_monitor,
        recovery,
        provider_manager,
        concurrency_controller,
    )

    return AppServices(
        settings=settings,
        redis=redis,
        queue=queue,
        provider_manager=provider_manager,
        concurrency_controller=concurrency_controller,
        tmux_manager=tmux_manager,
        classifier=classifier,
        session_monitor=session_monitor,
        recovery=recovery,
        worker=worker,
    )


def create_app(settings: Settings | None = None, redis_client: Redis | None = None) -> FastAPI:
    app_settings = settings or Settings()
    configure_logging(app_settings.log_level)
    services = build_services(app_settings, redis_client=redis_client)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.services = services
        worker_failure_task: asyncio.Task[None] | None = None
        if services.settings.enable_background_worker:
            await services.worker.start()
            worker_failure_task = asyncio.create_task(
                services.worker.wait_for_failure(),
                name="embedded-worker-failure",
            )
            worker_failure_task.add_done_callback(_crash_process_on_worker_failure)
        try:
            yield
        finally:
            if worker_failure_task is not None:
                worker_failure_task.cancel()
            if services.settings.enable_background_worker:
                await services.worker.stop()
            if worker_failure_task is not None:
                await asyncio.gather(worker_failure_task, return_exceptions=True)
            await services.redis.aclose()

    app = FastAPI(
        title=app_settings.app_name,
        description="Queue and supervise prompt-based claude/codex jobs running inside tmux.",
        version="0.2.0",
        lifespan=lifespan,
    )
    app.state.services = services
    app.include_router(health_router)
    app.include_router(jobs_router)
    return app


app = create_app()
