# AI Launcher Manager

`AI Launcher Manager` is a Dockerized FastAPI service that queues prompt-based `claude` and `codex` jobs in Redis, launches fixed interactive provider sessions inside `tmux`, waits for provider readiness, injects prompts only after readiness is confirmed, and monitors each session until it completes, retries, rate-limits, or fails.

This project is designed to be operable without reading the code. An operator or agent should be able to start the stack, submit jobs, inspect progress, understand state transitions, diagnose failures, and recover the system by reading the docs below.

## Read This First

Read the docs in this order:

1. `README.md` for setup and navigation
2. [docs/agent-runbook.md](docs/agent-runbook.md) for end-to-end operation
3. [docs/api-reference.md](docs/api-reference.md) for exact request/response contracts
4. [docs/architecture.md](docs/architecture.md) for lifecycle, recovery, and concurrency behavior

## What The App Does

- Accepts jobs through an HTTP API
- Stores queue and state in Redis
- Launches one dedicated `tmux` window per job
- Always uses fixed provider commands:
  - `codex --yolo`
  - `claude --dangerously-skip-permissions`
- Waits until the provider is ready before sending the prompt
- Uses `codex exec` as the primary runtime classifier for:
  - provider readiness
  - prompt-acceptance confirmation
  - Claude rate-limit / continue detection
  - terminal-state detection
- Adjusts concurrency separately for `codex` and `claude`
- Cleans up completed tmux windows automatically

## Quick Start

1. Review the environment settings in [ai-launcher-manager/.env.example](/mnt/c/Users/ruan.rodrigues/Documents/GitHub/prompts/ai-launcher-manager/.env.example).
2. Make sure the host machine has working auth for both CLIs if you plan to use them.
3. Start the stack:

```bash
cd ai-launcher-manager
docker compose up --build
```

4. Confirm health:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/metrics
curl http://localhost:8000/workers
```

5. Open the generated API docs:

- `http://localhost:8000/docs`

## Minimal Operating Example

Create a job:

```bash
curl -X POST http://localhost:8000/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "provider": "codex",
    "prompt": "Inspect the repository and summarize the main risks.",
    "priority": 80
  }'
```

List jobs:

```bash
curl http://localhost:8000/jobs
```

Inspect a single job:

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

## Important Operational Notes

- The API is prompt-based. Do not send raw shell commands to `/jobs`.
- The service currently reads runtime settings from `.env.example` because `docker-compose.yml` references that file directly.
- The worker runs inside the FastAPI process. There is no separate worker container.
- The main managed tmux session is named by `AILM_TMUX_SESSION_NAME`, which defaults to `ai-launcher-manager`.
- Finished tmux windows are expected to disappear automatically. If they do not, treat that as an operational issue.

## Documentation Map

- [docs/agent-runbook.md](docs/agent-runbook.md): how to operate the app without reading code
- [docs/api-reference.md](docs/api-reference.md): endpoints, payloads, fields, and example JSON
- [docs/architecture.md](docs/architecture.md): launch lifecycle, state machine, classifier contract, concurrency policy, and recovery

## Local Development

Install dependencies:

```bash
cd ai-launcher-manager
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

## Assumptions And Limits

- `codex` and `claude` CLIs must be installed and authenticated in the runtime environment.
- The codex-based classifier is the main interpreter, but deterministic fallbacks still exist.
- The service is an MVP and runs scheduling, monitoring, and recovery loops in one FastAPI process.
- Exact provider output can vary over time, so the docs describe behavior and contracts rather than brittle string matches.
