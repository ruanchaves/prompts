from __future__ import annotations

from datetime import timedelta

import fakeredis.aioredis
import pytest

from app.models.common import utcnow
from app.models.jobs import JobProvider, ProviderHealthEvent
from app.services.concurrency_controller import ConcurrencyController, ConcurrencySettings


def _settings(**overrides) -> ConcurrencySettings:
    defaults = dict(
        queue_namespace="ailm",
        initial_concurrency_per_provider=4,
        initial_concurrency_overrides={},
        min_concurrency_per_provider=1,
        concurrency_safety_ceiling=50,
        concurrency_increase_after_successes=2,
        high_water_mark_reset_seconds=3600,
    )
    defaults.update(overrides)
    return ConcurrencySettings(**defaults)


@pytest.mark.asyncio
async def test_additive_increase_on_success() -> None:
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = ConcurrencyController(redis_client, _settings())

    codex = await controller.get_state(JobProvider.CODEX)
    assert codex.current_limit == 4

    await controller.record_event(JobProvider.CODEX, ProviderHealthEvent.COMPLETED)
    codex = await controller.record_event(JobProvider.CODEX, ProviderHealthEvent.COMPLETED)
    assert codex.current_limit == 5  # +1 after 2 successes

    await redis_client.aclose()


@pytest.mark.asyncio
async def test_multiplicative_decrease_on_rate_limit() -> None:
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = ConcurrencyController(redis_client, _settings(initial_concurrency_per_provider=8))

    codex = await controller.record_event(JobProvider.CODEX, ProviderHealthEvent.RATE_LIMITED)
    assert codex.current_limit == 4  # 8 // 2 = 4

    await redis_client.aclose()


@pytest.mark.asyncio
async def test_multiplicative_decrease_respects_minimum() -> None:
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = ConcurrencyController(redis_client, _settings(initial_concurrency_per_provider=1))

    codex = await controller.record_event(JobProvider.CODEX, ProviderHealthEvent.RATE_LIMITED)
    assert codex.current_limit == 1  # cannot go below min

    await redis_client.aclose()


@pytest.mark.asyncio
async def test_high_water_mark_caps_increase() -> None:
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = ConcurrencyController(redis_client, _settings(
        initial_concurrency_per_provider=6,
        concurrency_increase_after_successes=1,
    ))

    # Rate limit at 6 -> halves to 3, sets high water mark at 6.
    codex = await controller.record_event(JobProvider.CODEX, ProviderHealthEvent.RATE_LIMITED)
    assert codex.current_limit == 3
    assert codex.high_water_mark == 6

    # Successes increase limit up to the high water mark, not the safety ceiling.
    for _ in range(5):
        codex = await controller.record_event(JobProvider.CODEX, ProviderHealthEvent.COMPLETED)

    # Should have climbed from 3 to min(3+5, high_water_mark=6) = 6, then stopped.
    # 3 -> 4 -> 5 -> 6 (3 increases), then 2 more completions just build streak.
    assert codex.current_limit == 6

    # One more success should NOT increase beyond high water mark.
    codex = await controller.record_event(JobProvider.CODEX, ProviderHealthEvent.COMPLETED)
    assert codex.current_limit == 6

    await redis_client.aclose()


@pytest.mark.asyncio
async def test_high_water_mark_expires() -> None:
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = ConcurrencyController(redis_client, _settings(
        initial_concurrency_per_provider=6,
        concurrency_increase_after_successes=1,
        high_water_mark_reset_seconds=3600,
    ))

    # Rate limit at 6, sets high water mark.
    codex = await controller.record_event(JobProvider.CODEX, ProviderHealthEvent.RATE_LIMITED)
    assert codex.high_water_mark == 6

    # Manually expire the high water mark by backdating it.
    codex.high_water_mark_set_at = utcnow() - timedelta(seconds=3601)
    await controller.save_state(codex)

    # Now climb back up: with expired HWM, the ceiling is 50 (safety).
    for _ in range(3):
        codex = await controller.record_event(JobProvider.CODEX, ProviderHealthEvent.COMPLETED)

    assert codex.current_limit == 6  # 3 -> 4 -> 5 -> 6

    # Should be able to go past the old HWM of 6 now.
    codex = await controller.record_event(JobProvider.CODEX, ProviderHealthEvent.COMPLETED)
    assert codex.current_limit == 7

    await redis_client.aclose()


@pytest.mark.asyncio
async def test_providers_tracked_independently() -> None:
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = ConcurrencyController(redis_client, _settings())

    await controller.record_event(JobProvider.CODEX, ProviderHealthEvent.RATE_LIMITED)
    codex = await controller.get_state(JobProvider.CODEX)
    claude = await controller.get_state(JobProvider.CLAUDE)

    assert codex.current_limit == 2  # 4 // 2 = 2
    assert claude.current_limit == 4  # untouched

    await redis_client.aclose()


@pytest.mark.asyncio
async def test_provider_specific_initial_override_applies_only_to_target_provider() -> None:
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = ConcurrencyController(
        redis_client,
        _settings(initial_concurrency_overrides={JobProvider.CODEX: 10}),
    )

    codex = await controller.get_state(JobProvider.CODEX)
    claude = await controller.get_state(JobProvider.CLAUDE)

    assert codex.current_limit == 10
    assert claude.current_limit == 4

    await redis_client.aclose()


@pytest.mark.asyncio
async def test_safety_ceiling_enforced() -> None:
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = ConcurrencyController(redis_client, _settings(
        initial_concurrency_per_provider=49,
        concurrency_safety_ceiling=50,
        concurrency_increase_after_successes=1,
    ))

    codex = await controller.record_event(JobProvider.CODEX, ProviderHealthEvent.COMPLETED)
    assert codex.current_limit == 50

    codex = await controller.record_event(JobProvider.CODEX, ProviderHealthEvent.COMPLETED)
    assert codex.current_limit == 50  # cannot exceed safety ceiling

    await redis_client.aclose()
