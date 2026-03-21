# Host Worker

This document explains exactly how to run the execution worker on the host.

## Purpose

The host worker is the process that actually:

- leases queued jobs from Redis
- opens and manages host `tmux` windows
- launches `codex --yolo` or `claude --dangerously-skip-permissions`
- injects prompts
- monitors output
- classifies session state with Codex
- handles retries, rate limits, and cleanup

The Docker API does not do any of this directly.

## Host Prerequisites

Before starting the host worker, verify:

- `tmux` is installed on the host
- `codex` is installed on the host
- `claude` is installed on the host
- both provider CLIs already work from the host shell
- the project virtualenv exists and dependencies are installed

Quick checks:

```bash
tmux -V
codex --version
claude --version
```

If the provider CLIs need interactive auth, complete that on the host before starting the worker.

## Start The Host Worker

From the project directory:

```bash
cd ai-launcher-manager
.venv/bin/python -m app.host_worker --env-file .env.host.example
```

What this does:

- loads settings from `.env.host.example`
- connects to Redis at `localhost:6381`
- creates or adopts the managed tmux session
- starts the scheduler, monitor, recovery, and heartbeat loops

## Stop The Host Worker

If you started it in the foreground, press `Ctrl-C`.

The worker traps `SIGINT` and `SIGTERM`, stops its loops, and closes Redis cleanly.

## Verify That The Worker Is Active

Check API health:

```bash
curl http://localhost:8003/health
```

Healthy shape:

```json
{
  "status": "ok",
  "redis": "ok",
  "tmux": "ok",
  "worker_count": 1
}
```

Check the worker heartbeat object:

```bash
curl http://localhost:8003/workers
```

Fields to inspect:

- `worker_id`
- `details.execution_target`
- `details.tmux_session_name`
- `details.tmux_session_exists`
- `details.provider_limits`
- `details.active_by_provider`

Expected values for the standard host worker:

- `details.execution_target` should be `host`
- `details.tmux_session_exists` should be `true`

## Inspect Host tmux

The default managed tmux session name is:

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

## How Auth Works Now

Provider auth is entirely host-side.

That means:

- the worker uses the same host environment that your shell uses
- Docker does not need auth volume mounts for `codex` or `claude`
- if a provider works in your host shell, the worker should see the same auth context

If auth fails now, debug it on the host first, not inside Docker.

## Common Failure Signals

If `/health` reports:

- `worker_count: 0`
  - the host worker is not running or cannot reach Redis
- `tmux: worker_missing`
  - no worker heartbeat is present
- `tmux: host_missing`
  - a worker heartbeat exists, but it is not reporting an active managed tmux session

If jobs stay in `queued`:

- confirm the host worker is running
- confirm `AILM_REDIS_URL` points to `redis://localhost:6381/0`
- confirm `/workers` shows at least one live worker

If jobs fail immediately after launch:

- run `codex --version` and `claude --version` on the host
- verify provider auth from the host shell
- inspect the relevant tmux window output
