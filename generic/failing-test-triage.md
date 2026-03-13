Fix the failing tests or checks using a coordinator session plus `tmux` workers
that run `codex --yolo`. Optimize for fast root-cause isolation, minimal fixes,
and targeted revalidation.

Inputs
- Repo root: `<repo_path>`
- Branch or PR: `<branch_or_pr>`
- Failing commands or logs: `<failures>`

Worker orchestration
- Keep the current shell as coordinator.
- Start one tmux worker per independent failure cluster:
  - `tmux new-session -d -s triage_<slug>_codex "cd <repo_path> && codex --yolo"`
- Good split examples:
  - backend unit failures
  - frontend build failures
  - lint or type-check failures
  - integration regressions
- Bad split examples:
  - two workers editing the same module
  - multiple workers retrying the same failing command

Workflow
1. Reproduce the failures with the smallest command that still fails.
2. Group failures by probable root cause.
3. Assign each group to a tmux worker with explicit ownership.
4. Each worker must:
   - identify the root cause
   - implement the smallest credible fix
   - rerun only the relevant checks
   - commit if its scope is complete
5. The coordinator integrates the fixes and runs the final targeted validation.

Rules
- Do not widen the command scope unless the narrow check is green.
- Do not paper over failures by deleting assertions or reducing coverage unless
  the behavior change is explicitly intended.
- If the environment or dependency setup is broken, report that directly instead
  of bootstrapping an ad hoc replacement.
- If a failure is flaky, capture the flake evidence and isolate it before
  changing production code.

Deliverable
- A clean summary of root causes, fixes, validation commands, and any residual
  risk or unverified paths.
