from __future__ import annotations

from redis.asyncio import Redis

from app.core.config import Settings
from app.models.jobs import JobProvider, ProviderConcurrencyRecord, ProviderHealthEvent, utcnow


class ConcurrencyController:
    def __init__(self, redis_client: Redis, settings: Settings) -> None:
        self.redis = redis_client
        self.settings = settings
        self.namespace = settings.queue_namespace

    def key(self, provider: JobProvider) -> str:
        return f"{self.namespace}:provider-concurrency:{provider.value}"

    def _default_record(self, provider: JobProvider) -> ProviderConcurrencyRecord:
        return ProviderConcurrencyRecord(
            provider=provider,
            current_limit=self.settings.initial_concurrency_per_provider,
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

    async def record_event(self, provider: JobProvider, event: ProviderHealthEvent) -> ProviderConcurrencyRecord:
        record = await self.get_state(provider)

        if event == ProviderHealthEvent.COMPLETED:
            record.total_completions += 1
            record.success_streak += 1
            record.failure_streak = 0
            if (
                record.success_streak >= self.settings.concurrency_increase_after_successes
                and record.current_limit < self.settings.max_concurrency_per_provider
            ):
                record.current_limit += 1
                record.success_streak = 0
        else:
            record.success_streak = 0
            record.failure_streak += 1
            if event == ProviderHealthEvent.RATE_LIMITED:
                record.total_rate_limits += 1
            else:
                record.total_failures += 1
            record.current_limit = max(
                self.settings.min_concurrency_per_provider,
                record.current_limit - self.settings.concurrency_decrease_step,
            )

        return await self.save_state(record)
