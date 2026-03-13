Review this pull request using a coordinator session plus `tmux` workers
running `codex --yolo`. Produce a findings-first review and an explicit risk
assessment.

Inputs
- Repo root: `<repo_path>`
- PR number or branch: `<pr_or_branch>`
- Base branch: `<base_branch>`

Worker orchestration
- Keep the current shell as the review coordinator.
- Start focused tmux review workers for independent areas:
  - `tmux new-session -d -s review_<pr>_backend_codex "cd <repo_path> && codex --yolo"`
  - `tmux new-session -d -s review_<pr>_frontend_codex "cd <repo_path> && codex --yolo"`
  - `tmux new-session -d -s review_<pr>_tests_codex "cd <repo_path> && codex --yolo"`
- Use only the workers that match the changed surface area.
- Each worker should inspect, not edit, unless you explicitly switch the review
  into a rework phase.

Review workflow
1. Read the PR description, linked issue, prior review comments, and latest CI
   state.
2. Inspect the diff and identify the highest-risk files first.
3. If the PR spans independent areas, assign those areas to tmux review
   workers.
4. Run only the targeted validation needed to confirm the highest-risk claims.
5. Write the review with findings first, ordered by severity.

Review output requirements
- Each finding must include:
  - severity
  - concrete behavior or regression risk
  - file references
  - why it matters
- If there are no findings, say that explicitly.
- End with:
  - `Risk assessment: low | medium | high`
  - `Merge recommendation: merge | rework | block`
  - `Validation: <commands run or not run>`

Rules
- Prefer primary evidence from code, tests, and docs over speculation.
- Do not hide uncertainty; call out unverified paths.
- If the PR is already low risk and merge-ready, say so plainly.
