# API Reference

This document describes the externally visible API contract for operating the service.

Base URL:

```text
http://localhost:8000
```

OpenAPI UI:

```text
http://localhost:8000/docs
```

## Common Job Object

The main job response includes these fields:

- `job_id`: unique id
- `provider`: `codex` or `claude`
- `prompt`: original submitted prompt
- `launch_command`: derived fixed launch command
- `priority`: integer from 0 to 100
- `retry_policy`
- `metadata`
- `state`
- `attempt_count`
- `prompt_attempt_count`
- `created_at`
- `updated_at`
- `started_at`
- `finished_at`
- `next_retry_at`
- `provider_ready_at`
- `prompt_sent_at`
- `prompt_confirmed_at`
- `last_rate_limit_at`
- `recovery_action`
- `active_prompt`
- `tmux_session`
- `tmux_window`
- `last_output`
- `last_output_hash`
- `last_output_at`
- `last_classification_at`
- `classifier_result`
- `failure_reason`
- `events`

## `POST /jobs`

Create a prompt job.

Request body:

```json
{
  "provider": "codex",
  "prompt": "Inspect the repository and summarize open risks.",
  "priority": 80,
  "retry_policy": {
    "max_attempts": 3,
    "initial_backoff_seconds": 30,
    "max_backoff_seconds": 600,
    "multiplier": 2.0,
    "cooldown_seconds": 60
  },
  "metadata": {
    "requested_by": "agent"
  }
}
```

Rules:

- `provider` is required
- `prompt` is required
- raw `command` input is not supported

Example response:

```json
{
  "job_id": "2b9432e0-4330-48e3-bed9-ef046c58a88e",
  "provider": "codex",
  "prompt": "Inspect the repository and summarize open risks.",
  "launch_command": "codex --yolo",
  "priority": 80,
  "state": "queued",
  "attempt_count": 0,
  "prompt_attempt_count": 0,
  "recovery_action": "none",
  "active_prompt": "Inspect the repository and summarize open risks.",
  "tmux_session": null,
  "tmux_window": null,
  "last_output": "",
  "failure_reason": null,
  "events": [
    {
      "state": "queued",
      "source": "api",
      "message": "Prompt job enqueued"
    }
  ]
}
```

## `GET /jobs`

List jobs.

Query parameters:

- `state`: optional filter
- `limit`: optional page size
- `offset`: optional offset

Example:

```bash
curl "http://localhost:8000/jobs?state=running&limit=20&offset=0"
```

Response shape:

```json
{
  "jobs": [],
  "total": 0
}
```

## `GET /jobs/{job_id}`

Fetch one job record.

Use this endpoint to inspect:

- current state
- retry timing
- tmux identifiers
- classifier reasoning
- recent output
- event history

Example:

```bash
curl http://localhost:8000/jobs/<job-id>
```

## `POST /jobs/{job_id}/cancel`

Cancel a non-terminal job.

Behavior:

- sends `Ctrl-C` to the tmux session if it still exists
- kills the managed tmux window
- marks the job as `cancelled`
- removes it from the schedule

## `POST /jobs/{job_id}/retry`

Manual retry for a non-running job.

Behavior:

- rejects retries for active lifecycle states
- resets prompt-delivery counters and readiness timestamps
- restores the original prompt as the pending prompt
- requeues the job immediately

## `GET /health`

Health check.

Response:

```json
{
  "status": "ok",
  "redis": "ok",
  "tmux": "ok",
  "worker_count": 1
}
```

Interpretation:

- `redis`: Redis connectivity from the app
- `tmux`: whether the managed tmux session exists
- `worker_count`: heartbeat count currently visible in Redis

## `GET /workers`

Worker heartbeat objects.

Each worker entry includes:

- `worker_id`
- `updated_at`
- `active_jobs`
- `details.tmux_session_name`
- `details.provider_limits`
- `details.active_by_provider`

## `GET /metrics`

Operational summary.

Response shape:

```json
{
  "counts_by_state": {
    "queued": 2,
    "running": 1
  },
  "total_jobs": 3,
  "provider_concurrency": [
    {
      "provider": "codex",
      "current_limit": 5,
      "success_streak": 1,
      "failure_streak": 0,
      "total_completions": 10,
      "total_failures": 1,
      "total_rate_limits": 0
    },
    {
      "provider": "claude",
      "current_limit": 4,
      "success_streak": 0,
      "failure_streak": 1,
      "total_completions": 8,
      "total_failures": 2,
      "total_rate_limits": 3
    }
  ]
}
```

Use this to understand:

- queue pressure
- current provider health
- whether concurrency is scaling up or backing off

## Job States

- `queued`: waiting in Redis schedule
- `launching`: tmux/provider launch is being created
- `waiting_for_provider_ready`: provider is live but prompt has not been injected yet
- `sending_prompt`: prompt was injected and acceptance is being confirmed
- `running`: prompt accepted and work appears active
- `waiting_for_classifier`: current snapshot is being classified
- `rate_limited`: retry is deferred to a specific time
- `retrying`: generic relaunch retry
- `completed`: successful terminal state
- `failed`: unsuccessful terminal state
- `stuck`: terminal no-progress state
- `cancelled`: manually cancelled terminal state

## `classifier_result`

The classifier result is the key explanation field.

It contains:

- `state`
- `confidence`
- `reason`
- `suggested_action`
- `provider_ready`
- `prompt_accepted`
- `recovery_action`
- `retry_at`
- `source`

Use it to answer:

- is the provider ready yet
- was the prompt actually accepted
- is this a Claude continue-style rate limit
- when will the system retry
- what recovery path was chosen

## Event History

Each job stores a short rolling event list.

Each event includes:

- `at`
- `state`
- `source`
- `message`

Use this to reconstruct:

- launch attempts
- readiness transitions
- prompt injection attempts
- rate-limit scheduling
- terminal outcomes
