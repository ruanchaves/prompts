# AI Launcher Manager

`AI Launcher Manager` is a Dockerized FastAPI service that queues prompt-based `claude` and `codex` jobs in Redis, launches fixed interactive provider sessions inside `tmux`, waits for provider readiness, injects prompts only after readiness is confirmed, and monitors each session until it completes, retries, rate-limits, or fails.

The main design choice is to use `codex exec` as the primary evaluator for:

- provider readiness
- prompt-acceptance confirmation
- runtime state detection
- Claude rate-limit / continue recovery decisions

Fallback heuristics still exist as safeguards when `codex` is unavailable or low-confidence.

## Features

- Redis-backed persistent queue and job state store
- FastAPI API with OpenAPI docs at `/docs`
- Prompt-based API contract: the service accepts `provider` + `prompt`
- Fixed launch commands:
  - `codex --yolo`
  - `claude --dangerously-skip-permissions`
- Dedicated `tmux` window per job
- Readiness detection before prompt injection
- Prompt-delivery retries when the message is sent too early
- Codex-first Claude rate-limit recovery
- Adaptive concurrency tracked separately for `codex` and `claude`
- Automatic cleanup of completed tmux windows
- Restart reconciliation for queued, partially launched, and rate-limited jobs

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

Create a prompt job:

```bash
curl -X POST http://localhost:8000/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "provider": "codex",
    "prompt": "Inspect the repository and summarize the open risks.",
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

## Launch Flow

1. A job is enqueued with `provider` and `prompt`.
2. The scheduler launches the fixed provider command in a dedicated `tmux` window.
3. The monitor captures pane output and asks `codex` whether the provider is ready.
4. Once ready, the monitor injects the pending prompt into the live tmux pane.
5. The monitor confirms that the prompt was actually accepted.
6. If the prompt was sent too early, the system retries prompt delivery safely.

## Claude Rate-Limit Recovery

When Claude hits a usage limit, the app does not rely mainly on brittle regexes. Instead, the classifier inspects recent Claude output and returns:

- whether Claude is in a continue-required limit state
- the interpreted retry time in local time
- whether the best next action is to:
  - press/trigger the continue path in the existing tmux session
  - or send:
    `Continue where you left off. The previous attempt was rate limited.`

Fallback parsing exists only as a safety net.

## Adaptive Concurrency

Concurrency is tracked per provider. Each provider starts at about 5 active sessions and then adapts independently:

- sustained successful completions increase the limit gradually
- failures, launch instability, stuck sessions, or rate limits reduce the limit

The current limits are exposed through `/metrics` and worker heartbeats.

## Project Layout

- `app/main.py`: FastAPI app factory and wiring
- `app/services/provider_manager.py`: fixed provider commands and continue message policy
- `app/services/concurrency_controller.py`: adaptive per-provider concurrency state
- `app/services/redis_queue.py`: Redis-backed queue and persistence
- `app/services/tmux_manager.py`: tmux launch, prompt injection, capture, termination, discovery
- `app/services/session_classifier.py`: codex + heuristic classification
- `app/services/session_monitor.py`: readiness gating, prompt delivery, runtime monitoring, rate-limit handling
- `app/services/recovery.py`: restart reconciliation
- `app/services/worker.py`: scheduler, monitor, and heartbeat loops
- `docs/architecture.md`: state-machine and operations notes

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

- The service runs its worker loops inside the FastAPI process.
- `codex` and `claude` CLIs are expected to be installed in the runtime image.
- The codex-based classifier improves flexibility but introduces model cost and uncertainty, so deterministic fallbacks still exist.
- Exact readiness text from interactive CLIs may vary over time, which is why the state evaluator is model-assisted rather than regex-only.

See [docs/architecture.md](docs/architecture.md) for the state machine, recovery behavior, and concurrency policy.
