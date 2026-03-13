Run a Trellint development wave using git worktrees plus `tmux` workers that
execute `codex --yolo`. The objective is to move multiple independent issues in
parallel without losing integration discipline.

Inputs
- Repo root: `<repo_path>`
- Stable branch: `<main_or_master>`
- Wave name: `<wave_name>`
- Issues in scope: `<issue_list>`

Branch and worktree model
- Create one wave branch:
  - `wave/<wave_name>`
- Create one issue branch and one worktree per issue:
  - `issue/<ticket>-<slug>`
  - worktree path example: `../<repo_name>-<ticket>`
- Keep each issue isolated to one worktree and one tmux worker.

Required worker model
- Keep the current shell as wave coordinator.
- For each issue worktree, start one tmux worker:
  - `tmux new-session -d -s wave_<ticket>_codex "cd <worktree_path> && codex --yolo"`
- Do not assign multiple unrelated issues to one worker.
- Require every worker to commit on its own issue branch before integration.

Execution workflow
1. Pull the stable branch and create `wave/<wave_name>`.
2. Add one worktree per issue branch.
3. Assign each worker:
   - exact issue scope
   - owned files or modules
   - target tests or checks
   - exit criteria
4. Each worker follows red/green/refactor where practical.
5. When a worker finishes, review its diff and merge the issue branch into the
   wave branch.
6. Keep the wave branch releasable after each merge.

Gate rules
- Run selective tests for each issue before integration.
- After integrating the wave, run the wave-level test gate.
- If the repo uses Docker or startup gates, run those with explicit timeouts.
- If a gate fails, create a narrow fix branch from the wave branch and start a
  dedicated tmux worker for that fix.

Trellint-specific notes
- In `chatbot`, respect `AGENTS.md`, use `./bin/python`, `./bin/pip`, and
  `./bin/pytest`, and prefer `timeout 120 ./bin/pytest ...`.
- In `rpp`, respect the documented local and Docker workflows and avoid broad
  validation unless the change is cross-cutting.

Completion criteria
- Every issue in the wave is committed on its own branch.
- The wave branch passes its required gates.
- The wave is ready for PR creation or merge into the stable branch.
