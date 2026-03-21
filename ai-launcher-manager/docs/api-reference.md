# API Reference

This document describes the externally visible API contract.

Base URL:

```text
http://localhost:8003
```

OpenAPI UI:

```text
http://localhost:8003/docs
```

## Deployment Assumption

The API is expected to run in Docker while the worker runs on the host.

Operational consequence:

- the API can be healthy while job execution is blocked if no host worker heartbeat is present
- `/workers` is part of the operational contract, not just debugging metadata

## Common Job Object

The main job object includes:

- `job_id`
- `provider`
- `prompt`
- `launch_command`
- `priority`
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
  "failure_reason": null
}
```

## `GET /jobs`

List jobs.

Query parameters:

- `state`
- `limit`
- `offset`

Example:

```bash
curl "http://localhost:8003/jobs?state=running&limit=20&offset=0"
```

## `GET /jobs/{job_id}`

Fetch one job record.

Use this to inspect:

- current state
- retry timing
- host tmux identifiers
- classifier reasoning
- recent output
- event history

Example:

```bash
curl http://localhost:8003/jobs/<job-id>
```

## `POST /jobs/{job_id}/cancel`

Cancel a job.

Behavior:

- terminal jobs cannot be cancelled
- queued or not-yet-running jobs move directly to `cancelled`
- active jobs move to `cancel_requested`
- the host worker observes `cancel_requested`, kills the host tmux window, and finalizes `cancelled`

Operational implication:

- `cancel_requested` is an expected transient state
- if a job stays in `cancel_requested`, the host worker is not keeping up or is unavailable

## `POST /jobs/{job_id}/retry`

Retry a non-running job.

Behavior:

- active lifecycle states cannot be retried
- prompt-delivery counters and readiness timestamps are reset
- the original prompt becomes the pending prompt again
- the job is requeued immediately

## `GET /health`

Health check.

Healthy example:

```json
{
  "status": "ok",
  "redis": "ok",
  "tmux": "ok",
  "worker_count": 1
}
```

Degraded example when the API is up but no host worker is present:

```json
{
  "status": "degraded",
  "redis": "ok",
  "tmux": "worker_missing",
  "worker_count": 0
}
```

Field meaning:

- `status`
  - `ok`: Redis is reachable and worker/tmux status is healthy
  - `degraded`: the API is up, but worker or tmux execution is not healthy
  - `error`: Redis is not reachable
- `redis`
  - API-to-Redis connectivity status
- `tmux`
  - `ok`: at least one worker reports a live managed tmux session
  - `worker_missing`: no worker heartbeat is visible
  - `host_missing`: a worker heartbeat exists but no live managed tmux session is reported
  - `missing`: only used in embedded-worker mode
- `worker_count`
  - number of visible worker heartbeats in Redis

## `GET /workers`

Worker heartbeat objects.

Each worker entry includes:

- `worker_id`
- `updated_at`
- `active_jobs`
- `details.execution_target`
- `details.tmux_session_name`
- `details.tmux_session_exists`
- `details.provider_limits`
- `details.active_by_provider`

For the standard deployment:

- `details.execution_target` should be `host`

## `GET /metrics`

Operational summary.

Response includes:

- `counts_by_state`
- `total_jobs`
- `provider_concurrency`

Use this to inspect:

- queue pressure
- provider health
- current adaptive concurrency limits

## Job States

- `queued`
- `launching`
- `waiting_for_provider_ready`
- `sending_prompt`
- `running`
- `waiting_for_classifier`
- `cancel_requested`
- `rate_limited`
- `retrying`
- `completed`
- `failed`
- `stuck`
- `cancelled`

State meaning:

- `cancel_requested`: the API accepted a live cancellation, but the host worker still needs to kill the tmux session
- `cancelled`: cancellation is complete
