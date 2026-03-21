# AI Launcher Manager

`AI Launcher Manager` is a Dockerized FastAPI service that queues `claude` and `codex` jobs in Redis, launches them inside `tmux`, and monitors each session until it is completed, retried, cancelled, or marked failed/stuck.

The primary design choice is session-state evaluation through `codex exec` instead of relying only on fixed output heuristics. Deterministic heuristics still exist as a fallback when `codex` is unavailable, low-confidence, or contradicted by clear process-level signals such as a zero/non-zero exit.

## Features

- Redis-backed persistent queue and job state store
- FastAPI API with OpenAPI docs at `/docs`
- Dedicated `tmux` window per job
- Background scheduler, monitor, recovery, and worker heartbeat loops
- Codex-first session classification with heuristic fallback
- Retry, backoff, cancellation, metrics, and restart reconciliation
- Docker and Docker Compose for local execution

## Quick Start

1. Copy the environment file:

   ```bash
   cp .env.example .env
   ```

2. Make sure your host has valid CLI auth for the tools you want to run.

   The compose file mounts:

   - `${HOME}/.codex` to `/root/.codex`
   - `${HOME}/.config/claude` to `/root/.config/claude`

3. Start the stack:

   ```bash
   docker compose up --build
   ```

4. Open the API docs:

   - `http://localhost:8000/docs`

## Example API Usage

Create a job:

```bash
curl -X POST http://localhost:8000/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "provider": "codex",
    "command": "codex --no-alt-screen exec \"summarize the repository\"",
    "priority": 80
  }'
```

List jobs:

```bash
curl http://localhost:8000/jobs
```

Inspect a job:

```bash
curl http://localhost:8000/jobs/<job-id>
```

Cancel a job:

```bash
curl -X POST http://localhost:8000/jobs/<job-id>/cancel
```

Retry a job:

```bash
curl -X POST http://localhost:8000/jobs/<job-id>/retry
```

## How State Detection Works

1. The monitor captures recent `tmux` pane output plus process metadata.
2. That context is sent to a `SessionStateClassifier`.
3. The primary classifier uses `codex exec` with a strict JSON schema.
4. If the codex result is unavailable, invalid, or low-confidence, fallback heuristics decide.
5. Deterministic exit signals override contradictory model output.

The exposed job states are:

- `queued`
- `starting`
- `running`
- `waiting_for_classifier`
- `idle`
- `rate_limited`
- `retrying`
- `completed`
- `failed`
- `stuck`
- `cancelled`

## Project Layout

- `app/main.py`: FastAPI app factory and lifespan wiring
- `app/services/redis_queue.py`: Redis-backed queue and persistence
- `app/services/tmux_manager.py`: tmux launch, capture, termination, discovery
- `app/services/session_classifier.py`: codex + heuristic classification
- `app/services/session_monitor.py`: monitoring loop and state transitions
- `app/services/recovery.py`: restart reconciliation
- `app/services/worker.py`: scheduler, monitor, and heartbeat loops
- `docs/architecture.md`: architecture and state-machine notes

## Local Development

Install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Run the API locally:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Run tests:

```bash
pytest
```

## Assumptions and Limitations

- The service is an MVP and runs its worker loops inside the FastAPI process.
- `codex` and `claude` CLIs are expected to be installed in the container image.
- Session classification cost is controlled by change-based and interval-based polling, but it is still model-backed and therefore non-zero cost.
- `tmux` output is easier to monitor when interactive CLIs are launched with flags like `--no-alt-screen`.

See [docs/architecture.md](docs/architecture.md) for the component breakdown and restart/retry behavior.
