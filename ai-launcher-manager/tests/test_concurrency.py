from __future__ import annotations

import fakeredis.aioredis
import pytest

from app.core.config import Settings
from app.models.jobs import JobProvider, ProviderHealthEvent
from app.services.concurrency_controller import ConcurrencyController


@pytest.mark.asyncio
async def test_adaptive_concurrency_is_tracked_per_provider() -> None:
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    settings = Settings(
        enable_background_worker=False,
        classifier_enabled=False,
        test_mode=True,
        initial_concurrency_per_provider=5,
        max_concurrency_per_provider=7,
        concurrency_increase_after_successes=2,
    )
    controller = ConcurrencyController(redis_client, settings)

    codex = await controller.get_state(JobProvider.CODEX)
    assert codex.current_limit == 5

    await controller.record_event(JobProvider.CODEX, ProviderHealthEvent.COMPLETED)
    codex = await controller.record_event(JobProvider.CODEX, ProviderHealthEvent.COMPLETED)
    assert codex.current_limit == 6

    codex = await controller.record_event(JobProvider.CODEX, ProviderHealthEvent.RATE_LIMITED)
    claude = await controller.get_state(JobProvider.CLAUDE)

    assert codex.current_limit == 5
    assert claude.current_limit == 5

    await redis_client.aclose()
