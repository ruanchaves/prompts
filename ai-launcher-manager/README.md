# AI Launcher Manager

`AI Launcher Manager` is a prompt-queueing FastAPI service for `codex` and `claude` jobs.

The queue and API run in Docker. The actual provider execution runs on the host through a standalone worker process. That host worker owns `tmux`, launches `codex --yolo` or `claude --dangerously-skip-permissions`, monitors session output, classifies runtime state with Codex, and cleans up finished windows.

This split exists on purpose:

- the API remains easy to run in Docker
- provider auth stays on the host
- `tmux`, `codex`, and `claude` do not need to run inside the container

## Read This First

Read the docs in this order:

1. `README.md`
2. [docs/operator-prompt.md](docs/operator-prompt.md)
3. [docs/host-worker.md](docs/host-worker.md)
4. [docs/agent-runbook.md](docs/agent-runbook.md)
5. [docs/api-reference.md](docs/api-reference.md)
6. [docs/architecture.md](docs/architecture.md)

## Execution Model

- Docker Compose starts:
  - `redis`
  - `api`
- The host starts:
  - `python -m app.host_worker`
- Redis is the boundary between them.
- The API never launches provider CLIs directly in Docker.
- The host worker is the only process that should touch managed tmux sessions.

## Quick Start

1. Verify host prerequisites:
   - `tmux` is installed on the host
   - `codex` is installed and authenticated on the host
   - `claude` is installed and authenticated on the host
   - the project virtualenv exists, or install dependencies first
2. Start Docker services:

```bash
cd ai-launcher-manager
docker compose up -d --build
```

3. Start the host worker in another shell:

```bash
cd ai-launcher-manager
.venv/bin/python -m app.host_worker --env-file .env.host.example
```

4. Verify health and worker heartbeat:

```bash
curl http://localhost:8003/health
curl http://localhost:8003/workers
curl http://localhost:8003/metrics
```

5. Open the API docs:

- `http://localhost:8003/docs`

## Ports And Env Files

- API host port: `8003`
- Redis host port: `6381`
- Docker API env file: `.env.example`
- Host worker env file: `.env.host.example`

Important details:

- inside Docker, the API still connects to Redis at `redis:6379`
- on the host, the worker connects to Redis at `localhost:6381`
- `.env.example` disables the embedded background worker in the API container
- `.env.host.example` enables the host worker and points it at host Redis

## Minimal Operating Example

Create a job:

```bash
curl -X POST http://localhost:8003/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "provider": "codex",
    "prompt": "Inspect the repository and summarize the main risks.",
    "priority": 80
  }'
```

List jobs:

```bash
curl http://localhost:8003/jobs
```

Inspect one job:

```bash
curl http://localhost:8003/jobs/<job-id>
```

Cancel a job:

```bash
curl -X POST http://localhost:8003/jobs/<job-id>/cancel
```

Retry a job:

```bash
curl -X POST http://localhost:8003/jobs/<job-id>/retry
```

## Important Operational Notes

- The API is prompt-based. Do not submit raw shell commands to `/jobs`.
- If the host worker is not running, jobs remain queued and `/health` reports a degraded state.
- Provider auth now comes entirely from the host environment, not from Docker volume mounts.
- A live cancel of an active job first moves the job to `cancel_requested`; the host worker then kills the tmux window and finalizes `cancelled`.
- The managed tmux session name defaults to `ai-launcher-manager`.
- Finished tmux windows should disappear automatically. If they do not, treat that as an operational issue on the host worker side.

## Documentation Map

- [docs/host-worker.md](docs/host-worker.md): exact host worker startup and inspection flow
- [docs/operator-prompt.md](docs/operator-prompt.md): master prompt for an agent to self-start and operate the system
- [docs/agent-runbook.md](docs/agent-runbook.md): end-to-end operation guide
- [docs/api-reference.md](docs/api-reference.md): endpoints, payloads, fields, and health semantics
- [docs/architecture.md](docs/architecture.md): queue model, worker split, lifecycle, recovery, and concurrency behavior

## Local Development

Install dependencies:

```bash
cd ai-launcher-manager
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Run the API locally:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Run the host worker locally against Docker Redis:

```bash
AILM_REDIS_URL=redis://localhost:6381/0 .venv/bin/python -m app.host_worker
```

Run tests:

```bash
pytest
```

## Assumptions And Limits

- The host worker is now required for provider execution.
- `codex` and `claude` must be installed and authenticated on the host.
- The codex-based classifier remains the main interpreter for readiness, prompt acceptance, Claude rate limits, and terminal-state detection.
- The service is still an MVP: one API process plus one or more host workers using Redis for coordination.
