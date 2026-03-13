Execute this task with a coordinator session plus `tmux` workers running
`codex --yolo` from the start. The goal is to finish the work quickly without
losing scope control, validation discipline, or file ownership.

Task
- Implement: `<task>`
- Repo root: `<repo_path>`
- Primary branch or PR: `<branch_or_pr>`

Worker orchestration
- Keep the current shell as the coordinator.
- For each independent workstream, launch a tmux worker:
  - `tmux new-session -d -s worker_<slug>_codex "cd <repo_path> && codex --yolo"`
- Limit concurrency to the number of truly independent workstreams.
- Give every worker a disjoint ownership boundary before it starts.
- If two streams need the same files, keep them in one worker instead of
  creating merge churn.
- Require every worker to commit its changes when done and report:
  - files changed
  - tests run
  - unresolved risks

Execution rules
- Inspect repo instructions and the relevant docs before editing.
- Prefer targeted tests and bounded commands over full-suite runs.
- Reproduce bugs before fixing them.
- Keep changes minimal and task-focused.
- Update tests or docs when behavior changes.
- Do not merge unfinished work.

Coordinator responsibilities
- Track active tmux sessions and unblock workers when they stall.
- Review each worker's diff before integrating it.
- Resolve conflicts centrally instead of having multiple workers fight over the
  same files.
- Run the final targeted validation after integration.
- Summarize what shipped, what was validated, and any remaining risk.

Stopping condition
- All required changes are implemented, committed, validated, and ready for the
  next review or merge step.
