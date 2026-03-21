from __future__ import annotations

from dataclasses import dataclass, field

from redis.asyncio import Redis

from app.models.jobs import JobProvider, ProviderConcurrencyRecord, ProviderHealthEvent, utcnow


@dataclass(frozen=True, slots=True)
class ConcurrencySettings:
    queue_namespace: str
    initial_concurrency_per_provider: int
    min_concurrency_per_provider: int
    concurrency_safety_ceiling: int
    concurrency_increase_after_successes: int
    high_water_mark_reset_seconds: int
    initial_concurrency_overrides: dict[JobProvider, int] = field(default_factory=dict)


class ConcurrencyController:
    def __init__(self, redis_client: Redis, settings: ConcurrencySettings) -> None:
        self.redis = redis_client
        self.settings = settings
        self.namespace = settings.queue_namespace

    def key(self, provider: JobProvider) -> str:
        return f"{self.namespace}:provider-concurrency:{provider.value}"

    def _initial_limit_for_provider(self, provider: JobProvider) -> int:
        return self.settings.initial_concurrency_overrides.get(
            provider,
            self.settings.initial_concurrency_per_provider,
        )

    def _default_record(self, provider: JobProvider) -> ProviderConcurrencyRecord:
        return ProviderConcurrencyRecord(
            provider=provider,
            current_limit=self._initial_limit_for_provider(provider),
        )

    async def get_state(self, provider: JobProvider) -> ProviderConcurrencyRecord:
        payload = await self.redis.get(self.key(provider))
        if payload is None:
            record = self._default_record(provider)
            await self.save_state(record)
            return record
        return ProviderConcurrencyRecord.model_validate_json(payload)

    async def save_state(self, record: ProviderConcurrencyRecord) -> ProviderConcurrencyRecord:
        record.updated_at = utcnow()
        await self.redis.set(self.key(record.provider), record.model_dump_json())
        return record

    async def list_states(self) -> list[ProviderConcurrencyRecord]:
        return [await self.get_state(provider) for provider in JobProvider]

    async def get_limit(self, provider: JobProvider) -> int:
        return (await self.get_state(provider)).current_limit

    def _effective_ceiling(self, record: ProviderConcurrencyRecord) -> int:
        """Return the effective ceiling, respecting the high water mark if fresh."""
        ceiling = self.settings.concurrency_safety_ceiling
        if record.high_water_mark is not None and record.high_water_mark_set_at is not None:
            age = (utcnow() - record.high_water_mark_set_at).total_seconds()
            if age < self.settings.high_water_mark_reset_seconds:
                ceiling = min(ceiling, record.high_water_mark)
        return ceiling

    async def record_event(self, provider: JobProvider, event: ProviderHealthEvent) -> ProviderConcurrencyRecord:
        record = await self.get_state(provider)

        if event == ProviderHealthEvent.COMPLETED:
            record.total_completions += 1
            record.success_streak += 1
            record.failure_streak = 0
            ceiling = self._effective_ceiling(record)
            if (
                record.success_streak >= self.settings.concurrency_increase_after_successes
                and record.current_limit < ceiling
            ):
                record.current_limit += 1
                record.success_streak = 0
        else:
            # Record the level that caused the failure as the high water mark.
            record.high_water_mark = record.current_limit
            record.high_water_mark_set_at = utcnow()

            record.success_streak = 0
            record.failure_streak += 1
            if event == ProviderHealthEvent.RATE_LIMITED:
                record.total_rate_limits += 1
            else:
                record.total_failures += 1

            # AIMD: multiplicative decrease (halve), clamped to min.
            record.current_limit = max(
                self.settings.min_concurrency_per_provider,
                record.current_limit // 2,
            )

        return await self.save_state(record)
