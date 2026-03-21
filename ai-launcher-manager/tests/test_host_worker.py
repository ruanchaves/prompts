from __future__ import annotations

import os
from pathlib import Path

from app.host_worker import load_env_file


def test_load_env_file_ignores_comments_and_sets_values(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / "worker.env"
    env_file.write_text(
        "# comment\n"
        "AILM_REDIS_URL=redis://localhost:6381/0\n"
        "\n"
        "AILM_WORKER_ID=host-worker-9\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("AILM_REDIS_URL", raising=False)
    monkeypatch.delenv("AILM_WORKER_ID", raising=False)

    load_env_file(env_file)

    assert os.environ["AILM_REDIS_URL"] == "redis://localhost:6381/0"
    assert os.environ["AILM_WORKER_ID"] == "host-worker-9"
