# Architecture

This document explains how the system behaves internally in the current host-execution model.

## Components

- `FastAPI`
  - accepts jobs
  - exposes health, worker, and metrics endpoints
  - runs in Docker
- `RedisQueue`
  - stores jobs, retry schedules, worker heartbeats, and concurrency state
- `Host WorkerService`
  - runs on the host
  - leases jobs from Redis
  - launches and monitors tmux sessions
- `ProviderManager`
  - defines the fixed provider commands and Claude continue message
- `TmuxManager`
  - owns the managed host tmux session
  - launches provider sessions
  - captures pane output
  - injects prompts
  - terminates or cleans up windows
- `CompositeSessionClassifier`
  - uses `codex --yolo` inside a PTY when the Codex classifier is enabled
  - falls back to heuristics only when the Codex classifier is explicitly disabled
  - treats classifier transport and low-confidence failures as fatal worker errors
- `SessionMonitor`
  - turns tmux snapshots into job-state transitions
- `ConcurrencyController`
  - tracks per-provider adaptive limits in Redis
- `RecoveryService`
  - re-adopts tmux windows and reconciles job state after worker restart

## Runtime Split

Docker runtime:

- API
- Redis

Host runtime:

- worker loop
- tmux server and windows
- `codex`
- `claude`

This split is intentional so provider auth and interactive tooling remain on the host.

## System Boundaries

The system is responsible for:

- queueing prompt jobs
- launching fixed provider sessions on the host
- deciding when to inject prompts
- monitoring long-running sessions
- retrying after failures or rate limits
- cleaning up finished host tmux windows

The system is not responsible for:

- authenticating provider CLIs for you
- storing provider credentials in Docker
- acting as a general shell-command runner

## Queue Model

Redis stores:

- one JSON record per job
- a sorted set of scheduled job ids
- worker heartbeats
- per-provider concurrency records

Operational implications:

- if Redis is lost, queue state is lost
- if the API restarts but Redis stays up, jobs remain available
- if the host worker restarts, it can recover from Redis plus host tmux state

## Fixed Provider Launch Model

The API accepts prompt jobs, not raw commands.

The host worker always launches one of these exact commands:

- `codex --yolo`
- `claude --dangerously-skip-permissions`

This matters because:

- readiness detection assumes interactive provider startup
- Claude rate-limit recovery assumes the live session can be resumed
- prompt reinjection assumes a stable provider shell

## Launch Lifecycle

The full lifecycle is:

1. API enqueues a prompt job in Redis
2. host worker leases the job
3. host worker opens or replaces the dedicated tmux window
4. host worker launches the fixed provider command
5. classifier evaluates provider readiness
6. worker injects the pending prompt through tmux buffers
7. classifier confirms prompt acceptance
8. worker monitors for:
   - progress
   - rate limits
   - failures
   - stuck behavior
   - completion
   - cancellation requests
9. worker cleans up the tmux window when the job becomes terminal

## Job States

- `queued`
- `launching`
- `waiting_for_provider_ready`
- `sending_prompt`
- `running`
- `cancel_requested`
- `rate_limited`
- `retrying`
- `completed`
- `failed`
- `stuck`
- `cancelled`

State interpretation:

- `waiting_for_provider_ready`: provider is running but prompt injection has not happened yet
- `sending_prompt`: the prompt was injected and acceptance is being confirmed
- `running`: the provider has accepted the prompt and the worker now throttles classifier calls using the min/max interval settings
- `cancel_requested`: the API accepted a live cancel and the host worker still needs to kill the tmux window
- `rate_limited`: the job is parked until `next_retry_at`

Legacy note:

- `waiting_for_classifier` may still appear on old persisted jobs during recovery, but the normal runtime path no longer stores that state

## Health And Heartbeats

The API does not inspect host tmux directly.

Instead, the host worker publishes heartbeats to Redis with:

- `execution_target`
- `tmux_session_name`
- `tmux_session_exists`
- `provider_limits`
- `active_by_provider`

The `/health` endpoint derives tmux health from those heartbeats when the embedded worker is disabled.

Operational consequence:

- `worker_missing` means no host worker heartbeat is present
- `host_missing` means a worker heartbeat exists but the managed tmux session is not reported as live

## Classifier Contract

The classifier receives:

- provider
- current job state
- prompt-attempt metadata
- pending prompt
- launch command
- local time and timezone
- recent tmux output
- pane exit metadata

It returns:

- lifecycle state
- confidence
- reason
- whether the provider is ready
- whether the prompt appears accepted
- suggested action
- optional retry time
- optional recovery action

The primary implementation uses `codex exec`.

## Readiness Detection

The worker never assumes the provider is ready immediately after launch.

Instead it waits for classifier evidence that:

- the provider is ready for prompt input
- or prompt acceptance already appears to have happened

This protects against:

- slow startup
- auth prompts
- splash screens
- session restoration output

## Prompt Injection

Prompt injection uses tmux buffers instead of shell-escaped command strings.

This preserves:

- multiline prompts
- exact retry content
- safer re-send behavior

After injection, the job moves to `sending_prompt` until prompt acceptance is confirmed.

## Claude Rate-Limit Recovery

Claude rate-limit handling is still classifier-driven.

The worker uses Codex to decide:

- whether the output is really the continue-style Claude rate-limit mode
- what local retry time should be used
- whether to:
  - press continue
  - send the continue message
  - relaunch the provider

The continue message is:

```text
Continue where you left off. The previous attempt was rate limited.
```

## Adaptive Concurrency

Concurrency is tracked separately for each provider in Redis.

- providers start at `AILM_INITIAL_CONCURRENCY_PER_PROVIDER` unless a provider-specific override is set; Codex can start at `AILM_INITIAL_CODEX_CONCURRENCY`
- successful completions gradually increase limits
- rate limits and failures reduce limits

Operational consequence:

- `codex` and `claude` can scale independently
- `/metrics` is the main source of truth for current limits

## Cancellation Model

Because provider execution happens on the host, active cancellation is a two-step process:

1. the API marks the job as `cancel_requested`
2. the host worker sees that state, kills the tmux window, and finalizes `cancelled`

Operational consequence:

- `cancel_requested` should be short-lived
- a stuck `cancel_requested` state usually means the host worker is down or unhealthy

## tmux Cleanup Policy

Terminal sessions are cleaned up automatically by the host worker.

Operational consequence:

- if a completed window remains on the host, cleanup failed or the worker stopped mid-transition

## Restart Recovery

On host worker startup, the recovery service:

1. ensures the managed host tmux session exists
2. re-schedules queued, retrying, and rate-limited jobs when needed
3. finalizes pending cancellations
4. preserves active jobs whose host tmux windows still exist
5. requeues active jobs whose windows disappeared if retries remain
6. removes lingering terminal windows

Operational consequence:

- queue state survives API restarts as long as Redis remains
- host tmux state survives API restarts because it is outside Docker
- host worker restart is the key recovery event for execution ownership
