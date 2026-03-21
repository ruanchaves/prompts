# Agent Runbook

This is the main operator guide for the current deployment model.

If you follow this runbook, you should be able to operate the service without reading the source code.

## Goal

Use the system to:

1. start the Docker API and Redis
2. start the host worker
3. submit prompt jobs
4. monitor job progress
5. inspect host tmux state
6. handle retries, cancellations, rate limits, and recovery

## Mental Model

The system is split into two runtimes:

- Docker runtime:
  - FastAPI API
  - Redis
- Host runtime:
  - worker loops
  - managed `tmux` session
  - `codex` and `claude` CLI execution

Redis is the shared coordination layer between them.

Operational consequence:

- if Docker is up but the host worker is down, the API still responds but jobs do not execute
- if the host worker is up but Redis is unavailable, the worker cannot lease or update jobs

## Preconditions

Before starting anything, verify:

- Docker is installed and running
- `docker compose` works
- the project virtualenv exists
- the host has working `tmux`
- the host has working `codex`
- the host has working `claude`
- provider auth is already valid on the host

Quick host-side checks:

```bash
tmux -V
codex --version
claude --version
```

If provider auth fails from the host shell, fix that first. Docker no longer carries provider auth mounts.

## Start The Stack

Start Docker services:

```bash
cd ai-launcher-manager
docker compose up -d --build
```

Start the host worker:

```bash
cd ai-launcher-manager
.venv/bin/python -m app.host_worker --env-file .env.host.example
```

Important facts:

- `.env.example` configures the Docker API container
- `.env.host.example` configures the host worker
- Redis is published on host port `6381`
- API is published on host port `8003`
- inside Docker, the API still uses `redis:6379`
- on the host, the worker uses `localhost:6381`

## Verify The Stack

Check health:

```bash
curl http://localhost:8003/health
```

Healthy example:

```json
{
  "status": "ok",
  "redis": "ok",
  "tmux": "ok",
  "worker_count": 1
}
```

Health interpretation:

- `status: ok`
  - Redis is reachable and at least one worker reports a healthy tmux session
- `status: degraded` with `tmux: worker_missing`
  - the API is up, but no host worker heartbeat is present
- `status: degraded` with `tmux: host_missing`
  - a worker heartbeat exists, but it is not reporting a live managed tmux session

Check worker heartbeats:

```bash
curl http://localhost:8003/workers
```

Check metrics:

```bash
curl http://localhost:8003/metrics
```

What to inspect:

- `worker_count`
- `details.execution_target`
- `details.tmux_session_exists`
- `counts_by_state`
- `provider_concurrency`

## Submit A Job

Send only:

- `provider`
- `prompt`
- optional priority / retry policy / metadata

Do not send raw shell commands.

Example:

```bash
curl -X POST http://localhost:8003/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "provider": "claude",
    "prompt": "Review the docs in this repo and propose missing operational checks.",
    "priority": 70,
    "metadata": {
      "requested_by": "operator"
    }
  }'
```

## What Happens After Submission

The normal job lifecycle is:

1. `queued`
2. `launching`
3. `waiting_for_provider_ready`
4. `sending_prompt`
5. `running`
6. one of:
   - `rate_limited`
   - `retrying`
   - `completed`
   - `failed`
   - `stuck`
   - `cancel_requested`
   - `cancelled`

The key behavior is unchanged:

- the worker first launches the fixed provider command
- it waits for readiness
- it injects the prompt only after readiness is confirmed

## Poll A Job

Inspect one job:

```bash
curl http://localhost:8003/jobs/<job-id>
```

Fields to watch:

- `state`
- `provider`
- `prompt`
- `launch_command`
- `attempt_count`
- `prompt_attempt_count`
- `next_retry_at`
- `provider_ready_at`
- `prompt_sent_at`
- `prompt_confirmed_at`
- `last_rate_limit_at`
- `recovery_action`
- `tmux_session`
- `tmux_window`
- `last_output`
- `classifier_result`
- `failure_reason`
- `events`

Interpretation:

- `cancel_requested` means the API accepted a live cancel request and the host worker still needs to kill the tmux window
- `rate_limited` means the job is intentionally parked until `next_retry_at`
- `tmux_session` and `tmux_window` refer to host tmux, not Docker tmux

## Inspect Host tmux Directly

The managed tmux session name defaults to:

```bash
ai-launcher-manager
```

List windows:

```bash
tmux list-windows -t ai-launcher-manager
```

Capture output for one job window:

```bash
tmux capture-pane -p -t ai-launcher-manager:job-<job-id> -S -200
```

Attach to the session:

```bash
tmux attach -t ai-launcher-manager
```

Operational rule:

- completed windows should not remain indefinitely
- if a completed window is still present, treat that as a host worker cleanup issue

## Readiness And Prompt Injection

The worker always launches one of these exact commands on the host:

- `codex --yolo`
- `claude --dangerously-skip-permissions`

Then it classifies live tmux output.

If the provider is not ready:

- the job remains in `waiting_for_provider_ready`

If the provider is ready:

- the worker injects the pending prompt through tmux buffers
- the job moves to `sending_prompt`

If prompt acceptance is confirmed:

- the job moves to `running`

If the prompt appears to have been injected too early:

- the worker retries prompt delivery up to the configured limit

## Claude Rate-Limit Handling

Claude rate-limit handling still works through Codex-based interpretation.

The worker uses Codex to decide:

- whether Claude is in a continue-required limit state
- what local retry time should be used
- whether to:
  - press continue
  - send the continue message
  - relaunch the provider

The continue message is:

```text
Continue where you left off. The previous attempt was rate limited.
```

Inspect these fields:

- `classifier_result`
- `recovery_action`
- `next_retry_at`
- `last_rate_limit_at`

## Adaptive Concurrency

Concurrency is still tracked separately per provider.

Check it with:

```bash
curl http://localhost:8003/metrics
```

Then inspect:

- `provider_concurrency[].provider`
- `provider_concurrency[].current_limit`
- `provider_concurrency[].success_streak`
- `provider_concurrency[].failure_streak`
- `provider_concurrency[].total_completions`
- `provider_concurrency[].total_failures`
- `provider_concurrency[].total_rate_limits`

## Retry And Cancel Operations

Cancel a job:

```bash
curl -X POST http://localhost:8003/jobs/<job-id>/cancel
```

Cancel behavior:

- queued or not-yet-running jobs move directly to `cancelled`
- active jobs move to `cancel_requested`
- the host worker then terminates the tmux session and finalizes `cancelled`

Retry a job:

```bash
curl -X POST http://localhost:8003/jobs/<job-id>/retry
```

Retry behavior:

- active jobs cannot be retried directly
- non-running jobs are requeued with prompt-delivery counters reset
- stale host windows are cleaned up on the next launch if necessary

## Restart Recovery

If the API container restarts:

- queued data remains in Redis
- host tmux windows remain on the host
- the host worker can continue processing once Redis/API are reachable again

If the host worker restarts:

- it re-adopts the managed tmux session
- it reconciles jobs with existing host windows
- it finalizes pending cancellations
- it requeues missing active windows when retries remain

After any restart, first run:

```bash
curl http://localhost:8003/health
curl http://localhost:8003/workers
curl http://localhost:8003/jobs
```

## Troubleshooting

Symptom: `/health` shows `worker_missing`

- start the host worker
- confirm the worker can reach Redis at `localhost:6381`
- check `/workers` again

Symptom: `/health` shows `host_missing`

- the worker is alive but not reporting a tmux session
- inspect the host worker logs
- run `tmux list-sessions` on the host

Symptom: jobs stay `queued`

- verify the host worker is running
- verify `/workers` is non-empty
- verify Redis is reachable on `6381`

Symptom: jobs fail immediately after launch

- inspect the host tmux window
- confirm provider auth from the host shell
- confirm `codex` and `claude` work outside Docker
