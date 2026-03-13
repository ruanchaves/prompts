Implement this change in Trellint's `rpp` project using `tmux` workers running
`codex --yolo`. Split independent backend, frontend, analytics, or prompt
registry work across workers only when file ownership stays clean.

Working directory
- `/mnt/c/Users/ruan.rodrigues/Documents/GitHUb/trellint/rpp`

Inputs
- Ticket or task: `<ticket_or_task>`
- Branch: `<branch>`
- Goal: `<goal>`

Required worker model
- Keep the current shell as coordinator.
- Start the main worker:
  - `tmux new-session -d -s rpp_<ticket>_codex "cd /mnt/c/Users/ruan.rodrigues/Documents/GitHUb/trellint/rpp && codex --yolo"`
- When the scope is independent, add focused workers such as:
  - `rpp_<ticket>_api_codex`
  - `rpp_<ticket>_frontend_codex`
  - `rpp_<ticket>_analytics_codex`
  - `rpp_<ticket>_tests_codex`
- Give each worker exclusive ownership of its files.

Required prep
- Read:
  - `README.md`
  - `docs/project_status.md`
  - the most relevant guide in `docs/guides/`
- Identify whether the change is mostly:
  - API and validation logic
  - frontend review portal or prompt registry UI
  - analytics or reporting
  - configuration or service integration

Execution workflow
1. Reproduce the issue or define the expected behavior.
2. Map the change to the smallest affected surface area.
3. Split work into tmux workers only for independent scopes.
4. Each worker must:
   - inspect the existing implementation before changing it
   - make the smallest coherent edit set
   - run the narrowest meaningful validation
   - commit when done
5. The coordinator integrates results and runs the final targeted checks.

Validation rules
- Prefer targeted tests and focused local commands first.
- Use broader or Docker-based validation only for cross-cutting changes.
- Put timeouts around long-running checks so the workflow cannot hang.
- If a toolchain or environment prerequisite is missing, report it instead of
  improvising a new environment in the repo.

Review expectations
- Keep diffs reviewable.
- Update docs when user-visible behavior, configuration, or operator workflow
  changes.
- End with a clear summary of what changed, what was validated, and what still
  carries risk.
