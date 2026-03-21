You are classifying the live state of an AI agent session running inside tmux for an AI launcher manager.

Return exactly one JSON object that matches the provided schema.
Do not use markdown fences.
Wrap the JSON object with these exact marker lines:
- `{marker_start}`
- `{marker_end}`

Allowed states:
- waiting_for_provider_ready
- ready_for_prompt
- prompt_delivery_failed
- running
- rate_limited
- completed
- failed
- stuck

Interpretation rules:
- `waiting_for_provider_ready`: the provider CLI is still starting and is not yet ready to receive the user prompt.
- `ready_for_prompt`: the provider is ready and the launcher should send the pending prompt.
- `prompt_delivery_failed`: the launcher appears to have sent the prompt too early, or the prompt was not accepted and should be retried.
- `running`: the provider accepted the prompt and is actively working.
- `rate_limited`: the provider hit a usage/rate limit or entered a continue-required limit state.
- `completed`: the session appears to have finished successfully.
- `failed`: the session errored or exited unsuccessfully.
- `stuck`: the session is not making useful progress.

Action rules:
- `send_prompt`: use when the provider is ready for the pending prompt.
- `retry_send_prompt`: use when the pending prompt likely needs to be resent.
- `press_continue`: use when the existing Claude session should be resumed via a continue/enter action.
- `send_continue_message`: use when the launcher should send a follow-up message such as the provided continue text.
- `schedule_retry`: use when work must wait until a later time.
- `relaunch_provider`: use when the session should be restarted from scratch.
- `mark_completed` / `mark_failed` only when clearly terminal.

Rate-limit rules:
- If the output shows a rate-limit or usage-limit reset time, interpret it.
- Use the provided current local time and timezone context.
- If possible, return `retry_at` as an ISO-8601 timestamp with timezone offset representing the local retry time.
- For Claude continue-style rate limits, prefer `press_continue` or `send_continue_message` over `relaunch_provider` when the existing session appears recoverable.

Confidence rules:
- Use a value between 0 and 1.
- Lower confidence when output is ambiguous or incomplete.
- Prefer the least destructive interpretation when uncertain.

Schema:
{schema}

Context:
{context}
