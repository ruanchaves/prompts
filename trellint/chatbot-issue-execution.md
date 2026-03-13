Implement this change in Trellint's `chatbot` project using `tmux` workers
running `codex --yolo`. Optimize for small scopes, targeted tests, and a clean
commit on the issue branch.

Working directory
- `/mnt/c/Users/ruan.rodrigues/Documents/GitHUb/trellint/chatbot`

Inputs
- Ticket or task: `<ticket_or_task>`
- Branch: `<branch>`
- Goal: `<goal>`

Required worker model
- Keep the current shell as coordinator.
- Start the main implementation worker in tmux:
  - `tmux new-session -d -s chatbot_<ticket>_codex "cd /mnt/c/Users/ruan.rodrigues/Documents/GitHUb/trellint/chatbot && codex --yolo"`
- If the work cleanly splits, start additional workers with disjoint ownership:
  - `chatbot_<ticket>_backend_codex`
  - `chatbot_<ticket>_frontend_codex`
  - `chatbot_<ticket>_tests_codex`
- Do not allow overlapping edits across workers.

Repo-specific rules
- Use the repo wrappers instead of raw Python tooling:
  - `./bin/python`
  - `./bin/pip`
  - `./bin/pytest`
- If needed, set `TRELLINT_PYTHON=/absolute/path/to/python`.
- Never create `.venv`, `venv`, or any other local environment.
- If `./bin/python` fails because the shared environment is missing, stop and
  report it.
- Run targeted tests only.
- Prefer `timeout 120 ./bin/pytest ...` for pytest commands.

Required prep
- Read:
  - `README.md`
  - `AGENTS.md`
  - `docs/guides/development_workflow.md`
  - `docs/guides/common_change_playbooks.md`
  - the closest relevant guide under `docs/guides/`

Execution workflow
1. Confirm the current branch or create a dedicated issue branch if needed.
2. Identify the exact files and tests affected.
3. Start with red/green where practical:
   - add or update a failing test or regression case
   - implement the minimum change to pass
   - refactor only while tests stay green
4. If the task touches intent handling, guardrails, prompts, or chat flows,
   inspect the existing playbooks before editing.
5. If the task touches frontend code, preserve the established UI patterns and
   avoid unrelated redesign.
6. Commit when the scope is complete.

Coordinator responsibilities
- Monitor all `chatbot_<ticket>*_codex` sessions.
- Review worker diffs before integrating them.
- Run the final targeted validation from the coordinator session.
- Summarize:
  - behavior changed
  - files touched
  - tests run
  - remaining risk

Stop only when the branch is ready for a new review or merge decision.
