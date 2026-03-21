from __future__ import annotations

from fastapi import APIRouter, Request

from app.models.jobs import HealthResponse, MetricsResponse, WorkerHeartbeat

router = APIRouter(tags=["system"])


def _services(request: Request):
    return request.app.state.services


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    services = _services(request)
    redis_status = "ok" if await services.queue.ping() else "error"
    tmux_status = "ok" if await services.tmux_manager.session_exists() else "missing"
    workers = await services.queue.list_workers()
    return HealthResponse(status="ok", redis=redis_status, tmux=tmux_status, worker_count=len(workers))


@router.get("/workers", response_model=list[WorkerHeartbeat])
async def workers(request: Request) -> list[WorkerHeartbeat]:
    services = _services(request)
    return await services.queue.list_workers()


@router.get("/metrics", response_model=MetricsResponse)
async def metrics(request: Request) -> MetricsResponse:
    services = _services(request)
    counts = await services.queue.counts_by_state()
    total = sum(counts.values())
    return MetricsResponse(counts_by_state=counts, total_jobs=total)
