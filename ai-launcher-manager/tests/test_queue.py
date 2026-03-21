from __future__ import annotations

import fakeredis.aioredis
import pytest

from app.models.jobs import JobCreateRequest, JobProvider, JobState
from app.services.redis_queue import RedisQueue, RedisQueueSettings


@pytest.mark.asyncio
async def test_create_and_lease_job_by_provider() -> None:
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    settings = RedisQueueSettings(queue_namespace="ailm", worker_heartbeat_ttl_seconds=20)
    queue = RedisQueue(redis_client, settings)

    created = await queue.create_job(
        JobCreateRequest(provider=JobProvider.CODEX, prompt="Fix the issue", priority=70)
    )
    leased = await queue.lease_next_job(JobProvider.CODEX, limit=1)

    assert leased is not None
    assert leased.job_id == created.job_id
    assert leased.state == JobState.QUEUED
    assert leased.active_prompt == "Fix the issue"
    assert await queue.count_active_jobs_by_provider(JobProvider.CODEX) == 1
    assert await queue.lease_next_job(JobProvider.CODEX, limit=1) is None

    await redis_client.aclose()
