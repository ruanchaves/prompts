from __future__ import annotations

import fakeredis.aioredis
import pytest

from app.core.config import Settings
from app.models.jobs import JobCreateRequest, JobProvider, JobState
from app.services.redis_queue import RedisQueue


@pytest.mark.asyncio
async def test_create_and_lease_job() -> None:
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    settings = Settings(enable_background_worker=False, classifier_enabled=False, test_mode=True)
    queue = RedisQueue(redis_client, settings)

    created = await queue.create_job(
        JobCreateRequest(provider=JobProvider.CODEX, command="echo hello", priority=70)
    )
    leased = await queue.lease_next_job()

    assert leased is not None
    assert leased.job_id == created.job_id
    assert leased.state == JobState.QUEUED

    await redis_client.aclose()
