Manage the open PR queue in a continuous loop until every PR is either merged or actively being advanced toward merge.

Definitions
- `<number>` = the PR number.
- A PR is considered `low risk for merge` only if its latest review says so and there are no blocking review comments, merge conflicts, or failing required checks.
- Use these exact tmux session names:
  - `pr_<number>_codex`
  - `review_<number>_codex`

Workflow

Step 1: Inspect open PRs
- Browse all open PRs and their full review/comment history.
- For each PR:
  - If it is low risk for merge, merge it immediately.
  - Otherwise, proceed to Step 2 for that PR.

Step 2: Continue work on non-low-risk PRs
- Start a tmux session named `pr_<number>_codex` running `codex --yolo`.
- Instruct the agent in that session to:
  1. Continue working on the PR on its existing branch, following the PR description and all review feedback.
  2. Commit its changes when finished.
  3. Do not merge the PR.
  4. Wait for a new code review after committing.
  5. Notify the user when the work is complete.

Step 3: Review completed work
- Continuously monitor all active `pr_<number>_codex` sessions.
- When a `pr_<number>_codex` session finishes:
  1. Kill that session.
  2. Start a new tmux session named `review_<number>_codex` running `codex --yolo`.
  3. Instruct the agent in that session to perform a fresh code review of the PR using the same review template as the previous review.
  4. The new review must include an updated risk assessment at the end.

Step 4: Loop
- When the `review_<number>_codex` session finishes, kill it.
- Return to Step 1 and repeat the full cycle.

Stopping condition
- Continue looping until all open PRs have become low risk for merge and have been merged.
