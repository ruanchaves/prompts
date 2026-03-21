from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import ResponseError, WatchError

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


@dataclass(frozen=True, slots=True)
class RedisQueueSettings:
    queue_namespace: str
    worker_heartbeat_ttl_seconds: int


class RedisQueue:
    LEASE_ACTIVE_SLOT_SCRIPT = """
local active = redis.call('SCARD', KEYS[2])
if active >= tonumber(ARGV[2]) then
  return 0
end
local removed = redis.call('ZREM', KEYS[1], ARGV[1])
if removed == 0 then
  return -1
end
redis.call('SADD', KEYS[2], ARGV[1])
return 1
"""

    def __init__(self, redis_client: Redis, settings: RedisQueueSettings) -> None:
        self.redis = redis_client
        self.namespace = settings.queue_namespace
        self._heartbeat_ttl = settings.worker_heartbeat_ttl_seconds

    @property
    def jobs_index_key(self) -> str:
        return f"{self.namespace}:jobs"

    @property
    def scheduled_key(self) -> str:
        return f"{self.namespace}:scheduled"

    def state_index_key(self, state: JobState) -> str:
        return f"{self.namespace}:state:{state.value}"

    def provider_state_index_key(self, provider: JobProvider, state: JobState) -> str:
        return f"{self.namespace}:provider-state:{provider.value}:{state.value}"

    def provider_active_key(self, provider: JobProvider) -> str:
        return f"{self.namespace}:provider-active:{provider.value}"

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

    def _index_keys(self) -> list[str]:
        keys = [self.jobs_index_key]
        for state in JobState:
            keys.append(self.state_index_key(state))
            for provider in JobProvider:
                keys.append(self.provider_state_index_key(provider, state))
        for provider in JobProvider:
            keys.append(self.provider_active_key(provider))
        return keys

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
        previous = await self.get_job(job.job_id)
        job.updated_at = utcnow()
        pipeline = self.redis.pipeline()
        if previous is not None:
            pipeline.srem(self.state_index_key(previous.state), job.job_id)
            pipeline.srem(self.provider_state_index_key(previous.provider, previous.state), job.job_id)
            pipeline.srem(self.provider_active_key(previous.provider), job.job_id)
        pipeline.set(self.job_key(job.job_id), job.model_dump_json(exclude_computed_fields=True))
        pipeline.sadd(self.jobs_index_key, job.job_id)
        pipeline.sadd(self.state_index_key(job.state), job.job_id)
        pipeline.sadd(self.provider_state_index_key(job.provider, job.state), job.job_id)
        if job.state in MONITORED_JOB_STATES:
            pipeline.sadd(self.provider_active_key(job.provider), job.job_id)
        else:
            pipeline.srem(self.provider_active_key(job.provider), job.job_id)
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

    async def rebuild_indexes(self) -> list[JobRecord]:
        pipeline = self.redis.pipeline()
        pipeline.delete(*self._index_keys())
        await pipeline.execute()

        jobs: list[JobRecord] = []
        async for key in self.redis.scan_iter(match=f"{self.namespace}:job:*"):
            payload = await self.redis.get(key)
            if payload:
                jobs.append(JobRecord.model_validate_json(payload))

        if not jobs:
            return []

        pipeline = self.redis.pipeline()
        for job in jobs:
            pipeline.sadd(self.jobs_index_key, job.job_id)
            pipeline.sadd(self.state_index_key(job.state), job.job_id)
            pipeline.sadd(self.provider_state_index_key(job.provider, job.state), job.job_id)
            if job.state in MONITORED_JOB_STATES:
                pipeline.sadd(self.provider_active_key(job.provider), job.job_id)
        await pipeline.execute()
        return jobs

    async def list_all_jobs(self) -> list[JobRecord]:
        job_ids = await self.redis.smembers(self.jobs_index_key)
        jobs = await self._load_jobs(job_ids)
        return sorted(jobs, key=lambda job: (job.created_at, job.priority), reverse=True)

    async def list_jobs(self, state: JobState | None = None, limit: int = 100, offset: int = 0) -> JobsListResponse:
        job_ids = await self.redis.smembers(self.jobs_index_key)
        jobs = await self._load_jobs(job_ids)
        if state is not None:
            jobs = [job for job in jobs if job.state == state]
        jobs.sort(key=lambda job: (job.created_at, job.priority), reverse=True)
        total = len(jobs)
        return JobsListResponse(jobs=jobs[offset : offset + limit], total=total)

    async def list_jobs_by_states(self, states: set[JobState]) -> list[JobRecord]:
        job_ids: set[str] = set()
        for state in states:
            ids = await self.redis.smembers(self.state_index_key(state))
            job_ids.update(ids)
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
        job_ids: set[str] = set()
        for state in states:
            ids = await self.redis.smembers(self.provider_state_index_key(provider, state))
            job_ids.update(ids)
        jobs = await self._load_jobs(job_ids)
        return sorted(
            [job for job in jobs if job.provider == provider and job.state in states],
            key=lambda job: (job.created_at, job.priority),
        )

    async def list_scheduled_job_ids(self) -> set[str]:
        scheduled = await self.redis.zrange(self.scheduled_key, 0, -1)
        return set(scheduled)

    async def _lease_candidate_with_watch(
        self,
        provider: JobProvider,
        candidate_id: str,
        limit: int,
    ) -> int:
        pipeline = self.redis.pipeline()
        try:
            await pipeline.watch(self.scheduled_key, self.provider_active_key(provider))
            active = int(await pipeline.scard(self.provider_active_key(provider)))
            if active >= limit:
                return 0
            score = await pipeline.zscore(self.scheduled_key, candidate_id)
            if score is None:
                return -1
            pipeline.multi()
            pipeline.zrem(self.scheduled_key, candidate_id)
            pipeline.sadd(self.provider_active_key(provider), candidate_id)
            result = await pipeline.execute()
            removed = int(result[0]) if result else 0
            return 1 if removed else -1
        except WatchError:
            return -1
        finally:
            await pipeline.reset()

    async def _lease_candidate_atomic(
        self,
        provider: JobProvider,
        candidate_id: str,
        limit: int,
    ) -> int:
        try:
            return int(
                await self.redis.eval(
                    self.LEASE_ACTIVE_SLOT_SCRIPT,
                    2,
                    self.scheduled_key,
                    self.provider_active_key(provider),
                    candidate_id,
                    limit,
                )
            )
        except ResponseError as exc:
            if "unknown command" not in str(exc).lower():
                raise
            return await self._lease_candidate_with_watch(provider, candidate_id, limit)

    async def lease_next_job(self, provider: JobProvider, limit: int) -> JobRecord | None:
        for _ in range(5):
            ready_ids = await self.redis.zrangebyscore(
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
            for candidate in candidates:
                result = await self._lease_candidate_atomic(provider, candidate.job_id, limit)
                if result == 1:
                    return candidate
                if result == 0:
                    return None
        return None

    async def count_active_jobs(self) -> int:
        total = 0
        for provider in JobProvider:
            total += await self.count_active_jobs_by_provider(provider)
        return total

    async def count_active_jobs_by_provider(self, provider: JobProvider) -> int:
        return int(await self.redis.scard(self.provider_active_key(provider)))

    async def record_worker_heartbeat(self, heartbeat: WorkerHeartbeat) -> None:
        await self.redis.set(
            self.worker_key(heartbeat.worker_id),
            heartbeat.model_dump_json(),
            ex=self._heartbeat_ttl,
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
        counts: dict[str, int] = {}
        for state in JobState:
            count = int(await self.redis.scard(self.state_index_key(state)))
            if count:
                counts[state.value] = count
        return counts
