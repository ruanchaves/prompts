from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI
from redis.asyncio import Redis, from_url

from app.api.routes.health import router as health_router
from app.api.routes.jobs import router as jobs_router
from app.core.config import Settings
from app.services.concurrency_controller import ConcurrencyController
from app.services.provider_manager import ProviderManager
from app.services.redis_queue import RedisQueue
from app.services.recovery import RecoveryService
from app.services.session_classifier import (
    CodexCliSessionClassifier,
    CompositeSessionClassifier,
    HeuristicSessionClassifier,
)
from app.services.monitor_orchestrator import MonitorOrchestrator
from app.services.session_monitor import SessionMonitor
from app.services.tmux_manager import TmuxManager
from app.services.worker import WorkerService
from app.utils.logging import configure_logging


@dataclass(slots=True)
class AppServices:
    settings: Settings
    redis: Redis
    queue: RedisQueue
    provider_manager: ProviderManager
    concurrency_controller: ConcurrencyController
    tmux_manager: TmuxManager
    classifier: CompositeSessionClassifier
    monitor_orchestrator: MonitorOrchestrator
    session_monitor: SessionMonitor
    recovery: RecoveryService
    worker: WorkerService


def build_services(settings: Settings, redis_client: Redis | None = None) -> AppServices:
    redis = redis_client or from_url(settings.redis_url, decode_responses=True)
    queue = RedisQueue(redis, settings)
    provider_manager = ProviderManager()
    concurrency_controller = ConcurrencyController(redis, settings)
    tmux_manager = TmuxManager(settings)
    classifier = CompositeSessionClassifier(
        settings=settings,
        primary=CodexCliSessionClassifier(settings, provider_manager),
        fallback=HeuristicSessionClassifier(settings, provider_manager),
    )
    monitor_orchestrator = MonitorOrchestrator(
        settings=settings,
        queue=queue,
        tmux_manager=tmux_manager,
        provider_manager=provider_manager,
        concurrency_controller=concurrency_controller,
    )
    session_monitor = SessionMonitor(
        settings=settings,
        queue=queue,
        tmux_manager=tmux_manager,
        classifier=classifier,
        orchestrator=monitor_orchestrator,
    )
    recovery = RecoveryService(settings, queue, tmux_manager, provider_manager)
    worker = WorkerService(
        settings,
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
        monitor_orchestrator=monitor_orchestrator,
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
        if services.settings.enable_background_worker:
            await services.worker.start()
        try:
            yield
        finally:
            if services.settings.enable_background_worker:
                await services.worker.stop()
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
