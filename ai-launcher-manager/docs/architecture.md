# Architecture

## Components

- `FastAPI`: API surface, OpenAPI docs, and process lifecycle
- `RedisQueue`: stores prompt jobs, scheduled retries, and worker heartbeats
- `ProviderManager`: defines the fixed launch commands and Claude continue message
- `TmuxManager`: launches provider sessions, captures pane output, injects prompts, sends continue actions, and kills completed windows
- `CompositeSessionClassifier`: uses `codex exec` first and falls back to heuristics
- `SessionMonitor`: waits for provider readiness, confirms prompt delivery, classifies runtime output, and schedules retries
- `ConcurrencyController`: tracks separate adaptive concurrency limits for `codex` and `claude`
- `RecoveryService`: reconciles Redis state and tmux windows after restart
- `WorkerService`: runs scheduler, monitor, and heartbeat loops

## Fixed Provider Launch Model

The API accepts prompt jobs, not arbitrary shell commands. The launcher always starts one of these exact provider sessions:

- `codex --yolo`
- `claude --dangerously-skip-permissions`

The launch lifecycle is:

1. queue job
2. open tmux window
3. launch fixed provider command
4. wait for provider readiness
5. inject pending prompt
6. confirm prompt acceptance
7. monitor until completion, retry, rate limit, or failure

## Job States

- `queued`: waiting for scheduler lease
- `launching`: tmux window is being created
- `waiting_for_provider_ready`: provider started, prompt not sent yet
- `sending_prompt`: pending prompt was injected and is awaiting confirmation
- `running`: prompt accepted and work is underway
- `waiting_for_classifier`: monitor is currently classifying the latest snapshot
- `rate_limited`: waiting until a classifier-selected retry time
- `retrying`: generic relaunch retry path
- `completed`: terminal success
- `failed`: terminal failure
- `stuck`: terminal no-progress state after retries are exhausted
- `cancelled`: operator-stopped terminal state

## Classifier Contract

The classifier receives:

- provider
- current job state
- prompt attempt metadata
- pending prompt
- launch command
- current local time and timezone
- recent tmux output
- pane exit metadata

It returns:

- lifecycle state
- confidence
- reason
- whether the provider is ready
- whether the prompt appears accepted
- suggested action
- optional local retry time
- recovery action such as:
  - `press_continue`
  - `send_continue_message`
  - `relaunch_provider`

## Claude Rate-Limit Recovery

Claude may stop in a continue-required rate-limit state. Instead of relying mainly on fixed regexes, the classifier interprets the output and decides:

- whether this is the continue-style Claude limit mode
- what retry time should be used in local time
- whether to:
  - press/trigger continue in the existing tmux session
  - send the continue message
  - relaunch the provider

If the codex classifier is unavailable or low-confidence, fallback parsing is used conservatively.

## Adaptive Concurrency

Concurrency is maintained separately for each provider in Redis.

- both providers start at `AILM_INITIAL_CONCURRENCY_PER_PROVIDER`
- repeated successful completions increase the limit gradually
- rate limits, launch failures, and other unhealthy outcomes decrease it

This is intentionally simple and operationally transparent, not a complex control system.

## tmux Cleanup Policy

Completed or terminal sessions are cleaned up automatically. The app kills finished tmux windows instead of leaving them hanging, which reduces instability and prevents orphaned finished sessions from accumulating.

## Restart Recovery

On startup the recovery service:

1. ensures the managed tmux session exists
2. re-schedules queued, retrying, and rate-limited jobs if scheduling metadata is missing
3. preserves partially launched sessions if their tmux windows still exist
4. requeues partially launched sessions whose windows disappeared
5. removes lingering finished windows for terminal jobs

## Operational Notes

- Prompt injection uses tmux buffers rather than naive shell escaping, which keeps multiline prompts intact.
- The codex classifier should be treated as the primary interpreter for readiness, prompt acceptance, and Claude limit messages.
- Heuristics remain as a fallback safety layer, not as the main control logic.
