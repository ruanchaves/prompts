from __future__ import annotations

from datetime import datetime
from typing import Iterable
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import WatchError

from app.core.config import Settings
from app.models.jobs import (
    JobCreateRequest,
    JobProvider,
    JobRecord,
    JobState,
    JobsListResponse,
    MONITORED_JOB_STATES,
    QUEUE_ELIGIBLE_JOB_STATES,
    WorkerHeartbeat,
    utcnow,
)


class RedisQueue:
    def __init__(self, redis_client: Redis, settings: Settings) -> None:
        self.redis = redis_client
        self.settings = settings
        self.namespace = settings.queue_namespace

    @property
    def jobs_index_key(self) -> str:
        return f"{self.namespace}:jobs"

    @property
    def scheduled_key(self) -> str:
        return f"{self.namespace}:scheduled"

    @property
    def workers_prefix(self) -> str:
        return f"{self.namespace}:workers:"

    def job_key(self, job_id: str) -> str:
        return f"{self.namespace}:job:{job_id}"

    def worker_key(self, worker_id: str) -> str:
        return f"{self.workers_prefix}{worker_id}"

    @staticmethod
    def _schedule_score(ready_at: datetime) -> float:
        return ready_at.timestamp()

    async def ping(self) -> bool:
        return bool(await self.redis.ping())

    async def create_job(self, payload: JobCreateRequest) -> JobRecord:
        now = utcnow()
        job = JobRecord(
            job_id=str(uuid4()),
            provider=payload.provider,
            prompt=payload.prompt,
            active_prompt=payload.prompt,
            priority=payload.priority,
            retry_policy=payload.retry_policy,
            metadata=payload.metadata,
            created_at=now,
            updated_at=now,
        )
        job.add_event(state=job.state, message="Prompt job enqueued", source="api")
        await self.save_job(job, schedule=True)
        return job

    async def save_job(
        self,
        job: JobRecord,
        *,
        schedule: bool | None = None,
        unschedule: bool = False,
    ) -> JobRecord:
        job.updated_at = utcnow()
        pipeline = self.redis.pipeline()
        pipeline.set(self.job_key(job.job_id), job.model_dump_json(exclude_computed_fields=True))
        pipeline.sadd(self.jobs_index_key, job.job_id)
        if schedule:
            ready_at = job.next_retry_at or utcnow()
            pipeline.zadd(self.scheduled_key, {job.job_id: self._schedule_score(ready_at)})
        if unschedule:
            pipeline.zrem(self.scheduled_key, job.job_id)
        await pipeline.execute()
        return job

    async def get_job(self, job_id: str) -> JobRecord | None:
        payload = await self.redis.get(self.job_key(job_id))
        if payload is None:
            return None
        return JobRecord.model_validate_json(payload)

    async def _load_jobs(self, job_ids: Iterable[str]) -> list[JobRecord]:
        ids = list(job_ids)
        if not ids:
            return []
        raw_jobs = await self.redis.mget([self.job_key(job_id) for job_id in ids])
        jobs: list[JobRecord] = []
        for payload in raw_jobs:
            if payload:
                jobs.append(JobRecord.model_validate_json(payload))
        return jobs

    async def list_jobs(self, state: JobState | None = None, limit: int = 100, offset: int = 0) -> JobsListResponse:
        job_ids = await self.redis.smembers(self.jobs_index_key)
        jobs = await self._load_jobs(job_ids)
        if state is not None:
            jobs = [job for job in jobs if job.state == state]
        jobs.sort(key=lambda job: (job.created_at, job.priority), reverse=True)
        total = len(jobs)
        return JobsListResponse(jobs=jobs[offset : offset + limit], total=total)

    async def list_jobs_by_states(self, states: set[JobState]) -> list[JobRecord]:
        job_ids = await self.redis.smembers(self.jobs_index_key)
        jobs = await self._load_jobs(job_ids)
        return sorted(
            [job for job in jobs if job.state in states],
            key=lambda job: (job.created_at, job.priority),
        )

    async def list_jobs_by_provider_and_states(
        self,
        provider: JobProvider,
        states: set[JobState],
    ) -> list[JobRecord]:
        jobs = await self.list_jobs_by_states(states)
        return [job for job in jobs if job.provider == provider]

    async def list_scheduled_job_ids(self) -> set[str]:
        scheduled = await self.redis.zrange(self.scheduled_key, 0, -1)
        return set(scheduled)

    async def lease_next_job(self, provider: JobProvider) -> JobRecord | None:
        for _ in range(5):
            pipeline = self.redis.pipeline()
            try:
                await pipeline.watch(self.scheduled_key)
                ready_ids = await pipeline.zrangebyscore(
                    self.scheduled_key,
                    min="-inf",
                    max=self._schedule_score(utcnow()),
                    start=0,
                    num=100,
                )
                if not ready_ids:
                    return None

                jobs = await self._load_jobs(ready_ids)
                candidates = [
                    job
                    for job in jobs
                    if job.provider == provider and job.state in QUEUE_ELIGIBLE_JOB_STATES
                ]
                if not candidates:
                    return None

                candidates.sort(
                    key=lambda job: (
                        job.next_retry_at or job.created_at,
                        -job.priority,
                        job.created_at,
                    )
                )
                candidate = candidates[0]
                pipeline.multi()
                pipeline.zrem(self.scheduled_key, candidate.job_id)
                result = await pipeline.execute()
                removed = int(result[0]) if result else 0
                if removed:
                    return candidate
            except WatchError:
                continue
            finally:
                await pipeline.reset()
        return None

    async def count_active_jobs(self) -> int:
        jobs = await self.list_jobs_by_states(MONITORED_JOB_STATES)
        return len(jobs)

    async def count_active_jobs_by_provider(self, provider: JobProvider) -> int:
        jobs = await self.list_jobs_by_provider_and_states(provider, MONITORED_JOB_STATES)
        return len(jobs)

    async def record_worker_heartbeat(self, heartbeat: WorkerHeartbeat) -> None:
        await self.redis.set(
            self.worker_key(heartbeat.worker_id),
            heartbeat.model_dump_json(),
            ex=self.settings.worker_heartbeat_ttl_seconds,
        )

    async def list_workers(self) -> list[WorkerHeartbeat]:
        workers: list[WorkerHeartbeat] = []
        async for key in self.redis.scan_iter(match=f"{self.workers_prefix}*"):
            payload = await self.redis.get(key)
            if payload:
                workers.append(WorkerHeartbeat.model_validate_json(payload))
        workers.sort(key=lambda heartbeat: heartbeat.updated_at, reverse=True)
        return workers

    async def counts_by_state(self) -> dict[str, int]:
        jobs = await self.list_jobs(limit=10_000)
        counts: dict[str, int] = {}
        for job in jobs.jobs:
            counts[job.state.value] = counts.get(job.state.value, 0) + 1
        return counts
