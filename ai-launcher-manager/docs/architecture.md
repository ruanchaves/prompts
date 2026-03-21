# Architecture

## Components

- `FastAPI`: API surface, OpenAPI docs, and process lifecycle
- `RedisQueue`: stores job records as JSON, maintains the scheduled queue, and publishes worker heartbeats
- `TmuxManager`: launches jobs, captures pane output, detects exits, and reconciles managed windows
- `CompositeSessionClassifier`: calls `codex exec` first and falls back to deterministic heuristics
- `SessionMonitor`: evaluates snapshots, applies state transitions, and schedules retries
- `RecoveryService`: reconciles Redis state and tmux windows after restart
- `WorkerService`: runs scheduler, monitor, and heartbeat loops in the background

## Queue Model

- Each job record is stored at `ailm:job:{job_id}` as JSON.
- All known jobs are indexed in `ailm:jobs`.
- Scheduled jobs are stored in `ailm:scheduled` as a sorted set keyed by next-ready timestamp.
- Worker heartbeats are stored under `ailm:workers:{worker_id}` with TTL.

## State Machine

- `queued`: waiting for the scheduler to lease it
- `starting`: scheduler is creating the tmux window
- `running`: launched and actively monitored
- `waiting_for_classifier`: a snapshot is being classified
- `idle`: the session appears paused or waiting for input
- `rate_limited`: rate-limited and scheduled to retry after cooldown/backoff
- `retrying`: generic retry delay after launch failure, crash, or stuck state
- `completed`: terminal success
- `failed`: terminal failure
- `stuck`: terminal state requiring operator action after retries are exhausted
- `cancelled`: operator-stopped terminal state

## Classification Flow

1. The monitor captures pane output and pane metadata from `tmux`.
2. Output changes or terminal signals trigger a classification request.
3. `codex exec` receives a compact JSON context and must return schema-valid JSON.
4. If codex is unavailable or low-confidence, heuristics evaluate:
   - zero/non-zero exits
   - rate-limit phrases
   - waiting-for-input phrases
   - long no-progress windows
5. The monitor maps the classification to a durable job state and either:
   - continues monitoring
   - schedules a retry
   - marks the job terminal

## Retry Strategy

- Retries use the job-level retry policy.
- The computed retry delay is `cooldown + exponential_backoff`.
- `rate_limited` and `retrying` states both re-enter the scheduled queue.
- Manual retry resets the attempt counter and requeues the same job record.

## Restart Recovery

On startup the recovery service:

1. Ensures the managed `tmux` session exists.
2. Re-schedules queued or retry-delayed jobs if they were lost from Redis scheduling metadata.
3. Reattaches monitored jobs if their tmux windows still exist.
4. Requeues monitored jobs whose windows disappeared, subject to retry budget.
5. Logs orphaned managed windows for operator follow-up.

## Operational Notes

- For the cleanest monitoring, launch `codex` jobs with `--no-alt-screen`.
- If you prefer to preserve failed/completed windows for inspection, keep `AILM_TMUX_CLEANUP_ON_TERMINAL_STATE=false`.
- If you want automatic pane cleanup after terminal states, set that flag to `true`.
