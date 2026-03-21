from __future__ import annotations

import fakeredis.aioredis
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_create_and_list_jobs_via_api() -> None:
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    settings = Settings(enable_background_worker=False, classifier_enabled=False, test_mode=True)
    app = create_app(settings=settings, redis_client=redis_client)

    with TestClient(app) as client:
        response = client.post(
            "/jobs",
            json={
                "provider": "codex",
                "command": "echo hello",
                "priority": 60,
            },
        )
        assert response.status_code == 201
        created = response.json()

        list_response = client.get("/jobs")
        assert list_response.status_code == 200
        payload = list_response.json()
        assert payload["total"] == 1
        assert payload["jobs"][0]["job_id"] == created["job_id"]
