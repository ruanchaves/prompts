# Prompt Library

Reusable prompts for engineering workflows.

Every prompt in this repo assumes a coordinator session plus `tmux` workers
running `codex --yolo` to keep work parallel, bounded, and reviewable.

## Layout

- `generic/`: reusable prompts that are not tied to one codebase
- `trellint/`: prompts tailored to `/mnt/c/Users/ruan.rodrigues/Documents/GitHUb/trellint`
- `continuous-pr-loop-prompt.md`: the original continuous PR management prompt

## Catalog

- `generic/parallel-issue-execution.md`: coordinate one or more independent
  implementation threads with tmux workers
- `generic/failing-test-triage.md`: reproduce, split, and fix failing tests or
  checks using targeted worker sessions
- `generic/bug-debugging-and-issue-comment.md`: scan open bug issues, improve
  logging around one issue, attempt reproduction, and post a signed debugging
  comment
- `generic/pr-review-and-risk-assessment.md`: review a PR with parallel area
  audits and an explicit merge-risk decision
- `trellint/chatbot-issue-execution.md`: deliver a change in the `chatbot`
  project using the shared Python environment and targeted pytest runs
- `trellint/rpp-feature-delivery.md`: implement a feature or fix in `rpp`
  across backend, frontend, analytics, or prompt-registry areas
- `trellint/parallel-wave-execution.md`: run a Trellint development wave with
  worktrees, issue branches, tmux workers, and integration gates
- `trellint/prompt-opportunity-scan.md`: scan the Trellint repo and the prompt
  library for missing prompt opportunities, then add or refine prompts
- `trellint/trellint-pr-review-and-rework-loop.md`: manage open Trellint PRs in
  a review/rework loop until they are low risk and ready to merge

Use the prompts as starting points and fill in the placeholders for the task,
ticket number, branch, or repo path you are working on.
