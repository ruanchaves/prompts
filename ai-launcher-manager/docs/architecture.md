# Architecture

This document explains how the system behaves internally so an operator can predict what it will do without reading the code.

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

## System Boundaries

The app is responsible for:

- queueing jobs
- starting provider sessions
- deciding when to inject prompts
- monitoring long-running sessions
- retrying after unhealthy events
- cleaning up finished windows

The app is not responsible for:

- authenticating the provider CLIs on your behalf
- managing separate worker containers
- acting as a general shell-command runner

## Queue Model

Redis stores:

- one JSON record per job
- a sorted set of scheduled job ids keyed by next eligible execution time
- worker heartbeats
- per-provider adaptive concurrency state

Operational implication:

- if Redis is lost, queue state is lost
- if the API process restarts but Redis remains, jobs can be recovered

## Fixed Provider Launch Model

The API accepts prompt jobs, not arbitrary shell commands.

The launcher always starts one of these exact provider sessions:

- `codex --yolo`
- `claude --dangerously-skip-permissions`

This is important because:

- readiness detection assumes an interactive provider shell
- rate-limit recovery assumes the live session can be resumed or prompted again
- the app is intentionally not a generic command queue

## Launch Lifecycle

The full lifecycle is:

1. queue job
2. lease job from Redis
3. open or replace the dedicated tmux window
4. launch the fixed provider command
5. classify the session until the provider appears ready
6. inject the pending prompt through tmux buffers
7. classify again until prompt acceptance appears confirmed
8. monitor for:
   - normal progress
   - rate limits
   - failures
   - stuck behavior
   - completion
9. clean up the tmux window if the job becomes terminal

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

State interpretation:

- `waiting_for_provider_ready` means launch succeeded but prompt injection has not happened yet
- `sending_prompt` means the prompt was injected but the monitor is still confirming the provider accepted it
- `rate_limited` means the job is intentionally parked until `next_retry_at`
- `retrying` means the app plans a fresh provider launch

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

Operational implication:

- if the codex classifier is healthy, behavior is flexible and message-aware
- if the classifier is unavailable or low-confidence, heuristics are used conservatively

## Readiness Detection

The app does not assume a provider is ready immediately after process start.

Instead it waits for the classifier to say one of:

- the provider is ready for prompt input
- the provider is still starting
- the prompt was already accepted

This matters because interactive CLIs can:

- draw a splash screen
- restore a prior session
- ask for auth or confirmation
- take time to initialize tools

## Prompt Injection And Confirmation

Prompt injection uses tmux buffers instead of naive shell escaping.

This was chosen so that:

- multiline prompts survive intact
- quoting is not fragile
- the app can re-send the exact same prompt during retries

After injection, the job enters `sending_prompt` and the monitor must confirm the prompt appears accepted. If not, it can retry prompt delivery without immediately relaunching the provider.

## Claude Rate-Limit Recovery

Claude may stop in a continue-required rate-limit state. Instead of relying mainly on fixed regexes, the classifier interprets the output and decides:

- whether this is the continue-style Claude limit mode
- what retry time should be used in local time
- whether to:
  - press/trigger continue in the existing tmux session
  - send the continue message
  - relaunch the provider

The continue message used by the system is:

```text
Continue where you left off. The previous attempt was rate limited.
```

Operational implication:

- `rate_limited` is not necessarily a failure
- Claude jobs may resume without a full relaunch if the existing session is still usable

## Adaptive Concurrency

Concurrency is maintained separately for each provider in Redis.

- both providers start at `AILM_INITIAL_CONCURRENCY_PER_PROVIDER`
- repeated successful completions increase the limit gradually
- rate limits, launch failures, and other unhealthy outcomes decrease it

This is intentionally simple and operationally transparent, not a complex control system.

Operational implication:

- Claude can back off while Codex keeps scaling, or vice versa
- `/metrics` is the main source of truth for current provider limits

## tmux Cleanup Policy

Completed or terminal sessions are cleaned up automatically. The app kills finished tmux windows instead of leaving them hanging, which reduces instability and prevents orphaned finished sessions from accumulating.

Operational implication:

- if a window is still present long after terminal completion, treat that as abnormal

## Restart Recovery

On startup the recovery service:

1. ensures the managed tmux session exists
2. re-schedules queued, retrying, and rate-limited jobs if scheduling metadata is missing
3. preserves partially launched sessions if their tmux windows still exist
4. requeues partially launched sessions whose windows disappeared
5. removes lingering finished windows for terminal jobs

Operational implication:

- a process restart should not lose queued work as long as Redis survived
- a live tmux window can be adopted after restart
- a missing live window usually leads to a requeue if retries remain

## Failure Modes

Common unhealthy paths are:

- provider failed to launch
- provider never became ready
- prompt was sent too early and not accepted
- provider hit a rate limit
- tmux window disappeared unexpectedly
- classifier judged the session as stuck
- provider process exited non-zero

The app reacts by:

- retrying prompt delivery
- parking a rate-limited job until `next_retry_at`
- relaunching the provider
- marking the job terminal when retries are exhausted

## Operational Notes

- The codex classifier should be treated as the primary interpreter for readiness, prompt acceptance, and Claude limit messages.
- Heuristics remain as a fallback safety layer, not as the main control logic.
- The fastest operator view is usually: `/health`, `/metrics`, then `/jobs/{job_id}`.
- The most useful manual inspection path is usually the tmux pane capture for one job window.
