Manage Trellint PRs in a continuous review and rework loop using `tmux`
sessions with `codex --yolo` workers. Continue until every open PR is either
merged or actively being advanced toward merge with a fresh review pending.

Definitions
- `<number>` = PR number
- Target repo = the Trellint subproject the PR belongs to, usually `chatbot` or
  `rpp`
- A PR is `low risk for merge` only if:
  - the latest review says so
  - there are no blocking comments
  - there are no unresolved merge conflicts
  - required checks are passing or intentionally waived
  - no obvious validation gap remains for the changed surface area

Required session names
- `pr_<number>_codex`
- `review_<number>_codex`
- Optional focused audit sessions:
  - `review_<number>_backend_codex`
  - `review_<number>_frontend_codex`
  - `review_<number>_tests_codex`

Step 1: Inspect open PRs
- Browse all open PRs and their full review and comment history.
- Determine whether each PR belongs to `chatbot`, `rpp`, or another Trellint
  worktree.
- For each PR:
  - If it is low risk for merge, merge it immediately.
  - Otherwise move it to Step 2.

Step 2: Rework non-low-risk PRs
- Start a tmux worker:
  - `tmux new-session -d -s pr_<number>_codex "cd <repo_or_worktree_path> && codex --yolo"`
- Instruct that worker to:
  1. Continue work on the PR branch, following the PR description and all prior
     review feedback.
  2. Read the repo instructions and relevant local docs before editing.
  3. Run only targeted validation for the touched behavior.
  4. Commit the changes when finished.
  5. Do not merge the PR.
  6. Notify the user when the branch is ready for a fresh review.

Trellint-specific execution rules
- For `chatbot` PRs:
  - use `./bin/python`, `./bin/pip`, and `./bin/pytest`
  - do not create a local `.venv`
  - prefer `timeout 120 ./bin/pytest ...`
- For `rpp` PRs:
  - use the documented local or Docker workflow already present in the repo
  - keep validation targeted unless the change is cross-cutting

Step 3: Review completed work
- Continuously monitor active `pr_<number>_codex` sessions.
- When a `pr_<number>_codex` session finishes:
  1. Kill that session.
  2. Start `review_<number>_codex`:
     - `tmux new-session -d -s review_<number>_codex "cd <repo_or_worktree_path> && codex --yolo"`
  3. If the PR spans clearly independent areas, optionally start focused audit
     sessions for backend, frontend, or tests.
  4. Perform a fresh code review using the same template as the previous review.
  5. End the review with:
     - findings first
     - updated risk assessment: `low`, `medium`, or `high`
     - merge recommendation
     - validation run or not run

Step 4: Loop
- When `review_<number>_codex` finishes, kill it.
- Return to Step 1.

Stopping condition
- Repeat the cycle until all open PRs are low risk for merge and have been
  merged.
