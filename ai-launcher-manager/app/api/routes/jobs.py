from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.models.jobs import JobCreateRequest, JobRecord, JobState, JobsListResponse, utcnow

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _services(request: Request):
    return request.app.state.services


@router.post("", response_model=JobRecord, status_code=status.HTTP_201_CREATED)
async def create_job(payload: JobCreateRequest, request: Request) -> JobRecord:
    services = _services(request)
    return await services.queue.create_job(payload)


@router.get("", response_model=JobsListResponse)
async def list_jobs(
    request: Request,
    state: JobState | None = None,
    limit: int = 100,
    offset: int = 0,
) -> JobsListResponse:
    services = _services(request)
    return await services.queue.list_jobs(state=state, limit=limit, offset=offset)


@router.get("/{job_id}", response_model=JobRecord)
async def get_job(job_id: str, request: Request) -> JobRecord:
    services = _services(request)
    job = await services.queue.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.post("/{job_id}/cancel", response_model=JobRecord)
async def cancel_job(job_id: str, request: Request) -> JobRecord:
    services = _services(request)
    job = await services.queue.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job.state == JobState.CANCELLED:
        return job
    if job.state in {JobState.COMPLETED, JobState.FAILED, JobState.STUCK}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Terminal jobs cannot be cancelled")

    await services.tmux_manager.terminate_job(job)
    job.next_retry_at = None
    job.transition(JobState.CANCELLED, "Job cancelled by operator", "api")
    await services.queue.save_job(job, unschedule=True)
    return job


@router.post("/{job_id}/retry", response_model=JobRecord)
async def retry_job(job_id: str, request: Request) -> JobRecord:
    services = _services(request)
    job = await services.queue.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job.state in {JobState.STARTING, JobState.RUNNING, JobState.WAITING_FOR_CLASSIFIER, JobState.IDLE}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Running jobs cannot be retried")

    job.attempt_count = 0
    job.next_retry_at = utcnow()
    job.failure_reason = None
    job.transition(JobState.RETRYING, "Manual retry requested", "api")
    await services.queue.save_job(job, schedule=True)
    return job
