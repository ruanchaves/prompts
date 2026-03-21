# Agent Runbook

This document is the primary operating guide for an AI agent or human operator. If you follow this runbook, you should not need to read the source code to use the system safely.

## Goal

Use the app to:

1. start the stack
2. submit prompt jobs
3. monitor job progress
4. inspect runtime state
5. understand failures and rate limits
6. retry, cancel, or recover jobs

## Mental Model

One API process does all of the following:

- accepts jobs over HTTP
- stores job records and schedules in Redis
- launches provider CLIs inside `tmux`
- uses `codex` to determine whether sessions are ready, running, stuck, rate-limited, or complete
- increases or decreases concurrency per provider over time

Each job corresponds to one tmux window inside one managed tmux session.

## Preconditions

Before starting the stack, verify:

- Docker is installed and running
- `docker compose` works
- the host has valid credentials for:
  - `codex`
  - `claude`
- the auth paths used by `docker-compose.yml` exist:
  - `${HOME}/.codex`
  - `${HOME}/.config/claude`

If Claude or Codex auth is missing, the provider may launch and then immediately fail inside tmux.

## Start The Stack

From the project directory:

```bash
cd ai-launcher-manager
docker compose up --build
```

Important:

- `docker-compose.yml` currently points the container env to `.env.example`
- if you want different settings, edit `.env.example` or adjust the compose file

## Verify The Stack

Check API health:

```bash
curl http://localhost:8000/health
```

Expected shape:

```json
{
  "status": "ok",
  "redis": "ok",
  "tmux": "ok",
  "worker_count": 1
}
```

Check worker heartbeats:

```bash
curl http://localhost:8000/workers
```

Check metrics:

```bash
curl http://localhost:8000/metrics
```

What to look for:

- `counts_by_state`: current system load by job state
- `provider_concurrency`: separate adaptive limits for `codex` and `claude`

## Submit A Job

Send only:

- `provider`
- `prompt`
- optional priority / retry policy / metadata

Do not send a raw shell command. The service will ignore that contract and reject invalid payloads.

Example:

```bash
curl -X POST http://localhost:8000/jobs \
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

The job lifecycle is:

1. `queued`
2. `launching`
3. `waiting_for_provider_ready`
4. `sending_prompt`
5. `running`
6. terminal or retry path:
   - `rate_limited`
   - `retrying`
   - `completed`
   - `failed`
   - `stuck`
   - `cancelled`

The key point is that the app does not send the prompt immediately after launching the provider. It waits until the classifier believes the provider is ready.

## Poll A Job

Inspect one job:

```bash
curl http://localhost:8000/jobs/<job-id>
```

Fields you should pay attention to:

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

- `attempt_count`: number of provider launch attempts
- `prompt_attempt_count`: number of prompt send attempts for the current session
- `active_prompt`: pending prompt that will be sent next
- `recovery_action`: what the app plans to do after a rate limit or recovery event

## Inspect tmux Directly

The managed tmux session name defaults to:

```bash
ai-launcher-manager
```

List windows:

```bash
tmux list-windows -t ai-launcher-manager
```

Capture pane output for one job window:

```bash
tmux capture-pane -p -t ai-launcher-manager:job-<job-id> -S -200
```

Attach to the full session:

```bash
tmux attach -t ai-launcher-manager
```

Operational rule:

- completed windows should not remain indefinitely
- if a completed window is still present, inspect the job state and recent output

## How Readiness And Prompt Injection Work

The service always launches one of these exact commands:

- `codex --yolo`
- `claude --dangerously-skip-permissions`

Then it classifies the live terminal output.

If the classifier believes the provider is not ready:

- the job stays in `waiting_for_provider_ready`

If the classifier believes the provider is ready:

- the service injects the pending prompt through tmux buffers
- the job moves to `sending_prompt`

If the prompt appears accepted:

- the job moves to `running`

If the prompt appears to have been sent too early:

- the job remains on the prompt-delivery path
- the service retries prompt delivery up to `AILM_MAX_PROMPT_DELIVERY_ATTEMPTS`

## Claude Rate-Limit Handling

Claude can stop in a state that requires a manual continue path. The message text may vary. The system uses `codex` to infer:

- whether the message is actually a rate-limit / continue state
- what retry time should be used in local time
- whether recovery should be:
  - `press_continue`
  - `send_continue_message`
  - `relaunch_provider`

When the selected recovery action is `send_continue_message`, the service sends:

```text
Continue where you left off. The previous attempt was rate limited.
```

How to inspect this:

- check `classifier_result`
- check `recovery_action`
- check `next_retry_at`
- check `last_rate_limit_at`

## Adaptive Concurrency

The app keeps a separate concurrency record for each provider.

Default behavior:

- start at `AILM_INITIAL_CONCURRENCY_PER_PROVIDER`
- increase after repeated successful completions
- decrease after rate limits, launch failures, stuck jobs, or failures

Check current values:

```bash
curl http://localhost:8000/metrics
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
curl -X POST http://localhost:8000/jobs/<job-id>/cancel
```

Retry a job manually:

```bash
curl -X POST http://localhost:8000/jobs/<job-id>/retry
```

Manual retry behavior:

- resets prompt-delivery counters
- clears readiness timestamps
- requeues the original prompt
- attempts a fresh provider lifecycle

## Restart Recovery

If the API process restarts:

- queued jobs are re-scheduled if needed
- rate-limited jobs remain scheduled
- active jobs with existing windows are preserved
- active jobs whose windows disappeared are requeued if retries remain
- finished windows are removed for terminal jobs

After a restart, the first checks should be:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/workers
curl http://localhost:8000/jobs
```

## Environment Settings

The main settings in `.env.example` are:

- `AILM_REDIS_URL`: Redis connection string
- `AILM_SCHEDULER_POLL_INTERVAL_SECONDS`: how often the scheduler looks for work
- `AILM_MONITOR_POLL_INTERVAL_SECONDS`: how often the monitor re-checks active sessions
- `AILM_TMUX_SESSION_NAME`: top-level tmux session name
- `AILM_TMUX_HISTORY_LINES`: number of lines captured for classification
- `AILM_TMUX_CLEANUP_ON_TERMINAL_STATE`: whether terminal windows are killed automatically
- `AILM_CLASSIFIER_ENABLED`: disable only for debugging fallback behavior
- `AILM_CLASSIFIER_COMMAND`: classifier executable, usually `codex`
- `AILM_CLASSIFIER_TIMEOUT_SECONDS`: max duration for one classification call
- `AILM_CLASSIFIER_MIN_CONFIDENCE`: fallback threshold
- `AILM_PROMPT_DELIVERY_TIMEOUT_SECONDS`: timeout before prompt send is treated as failed
- `AILM_MAX_PROMPT_DELIVERY_ATTEMPTS`: prompt send retries before failure
- `AILM_INITIAL_CONCURRENCY_PER_PROVIDER`: starting provider limit
- `AILM_MIN_CONCURRENCY_PER_PROVIDER`: floor for adaptive backoff
- `AILM_MAX_CONCURRENCY_PER_PROVIDER`: cap for adaptive growth
- `AILM_CONCURRENCY_INCREASE_AFTER_SUCCESSES`: completions required before increasing limit
- `AILM_CONCURRENCY_DECREASE_STEP`: how much to reduce after unhealthy events
- `AILM_LOCAL_TIMEZONE`: timezone used for rate-limit retry interpretation

## Troubleshooting

Symptom: `/health` shows `tmux: missing`

- the worker may not have created the managed tmux session yet
- wait one scheduler cycle and check again
- if it persists, inspect container logs

Symptom: jobs stay in `waiting_for_provider_ready`

- inspect `last_output`
- inspect the tmux pane directly
- check whether provider auth or startup prompts are blocking
- confirm `codex` classifier access still works

Symptom: jobs bounce between `sending_prompt` and retry behavior

- the provider is likely not actually ready when the prompt is injected
- inspect `last_output`
- inspect `prompt_attempt_count`
- consider increasing `AILM_PROMPT_DELIVERY_TIMEOUT_SECONDS`

Symptom: many `rate_limited` Claude jobs

- inspect `/metrics`
- verify `provider_concurrency` is backing off
- inspect one job’s `classifier_result` and `next_retry_at`

Symptom: completed jobs still have tmux windows

- this should not be normal
- inspect job state
- inspect worker logs
- manually list windows in the managed tmux session

Symptom: no worker heartbeat

- check `/workers`
- inspect container logs
- verify the FastAPI process is still running with background work enabled

## When To Read The Code Anyway

You should not need the code for normal operation. Read the code only if:

- the documented API behavior does not match the live responses
- the classifier is returning malformed data repeatedly
- tmux behavior differs from the runbook
- a new provider is being added
