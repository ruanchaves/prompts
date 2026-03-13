Scan the Trellint workspace for new prompt opportunities using a coordinator
session plus `tmux` workers running `codex --yolo`. The goal is to expand the
prompt library only where there is clear evidence of a repeated workflow,
manual procedure, or recurring debugging/review pattern that is not already
well-covered.

Working directories
- Trellint workspace: `/mnt/c/Users/ruan.rodrigues/Documents/GitHUb/trellint`
- Prompt library: `/mnt/c/Users/ruan.rodrigues/Documents/GitHUb/prompts`

Required worker model
- Keep the current shell as coordinator in the `prompts` repo.
- Start focused scan workers in tmux:
  - `tmux new-session -d -s prompt_scan_chatbot_codex "cd /mnt/c/Users/ruan.rodrigues/Documents/GitHUb/trellint/chatbot && codex --yolo"`
  - `tmux new-session -d -s prompt_scan_rpp_codex "cd /mnt/c/Users/ruan.rodrigues/Documents/GitHUb/trellint/rpp && codex --yolo"`
  - `tmux new-session -d -s prompt_scan_docs_codex "cd /mnt/c/Users/ruan.rodrigues/Documents/GitHUb/trellint && codex --yolo"`
- Add more workers only if the ownership boundary is clean.
- Do not let two workers propose or edit the same prompt file.

Scan targets
- `README.md` files
- `AGENTS.md`
- `docs/guides/`
- `docs/architecture/`
- recurring issue and PR workflows
- scripts or commands that are repeatedly run by hand
- worktree, debugging, testing, release, and review procedures
- places where prior tasks required custom orchestration that should become a
  reusable prompt

Discovery workflow
1. Inventory the existing prompt library first.
2. Scan Trellint for repeated workflows, pain points, and manual coordination
   patterns.
3. Compare those findings against the existing prompts.
4. Identify only high-value gaps such as:
   - workflows repeated across multiple tasks
   - multi-step procedures with many chances for omission
   - debugging or review routines that benefit from structured output
   - repo-specific execution patterns that are not obvious from the code alone
5. Reject low-value prompt ideas:
   - one-off tasks
   - prompts that duplicate an existing prompt with only cosmetic differences
   - prompts that are so broad they would become vague and low-signal

Classification rules
- If the prompt is mainly useful only inside Trellint, save it under
  `trellint/`.
- If the workflow is broadly reusable outside Trellint, save it under
  `generic/`.
- Update `README.md` whenever a prompt is added, renamed, or materially changed.

Prompt authoring rules
- Every prompt must explicitly require `tmux` sessions with `codex --yolo`
  workers.
- Every prompt should define:
  - inputs
  - worker naming or ownership
  - execution workflow
  - validation or output expectations
  - stopping condition
- Make the prompts operational, not abstract.
- Prefer concrete paths, commands, and decision rules where the repo has stable
  conventions.

Trellint-specific considerations
- For `chatbot`, respect `AGENTS.md`, the shared Python wrappers, targeted pytest
  usage, and the documented workflow guides.
- For `rpp`, use the documented local, frontend, analytics, and Docker
  workflows instead of inventing a new toolchain.
- Pay attention to multi-worktree issue execution and PR-review loops already
  used in this workspace.

Execution workflow
1. Run the scan with tmux workers.
2. Gather candidate prompt ideas with evidence:
   - where the workflow appears
   - why it is repeated or error-prone
   - why the current prompt library does not cover it
3. Prioritize the strongest candidates.
4. Add or refine the prompt files in the `prompts` repo.
5. Update the prompt catalog in `README.md`.
6. Review the new prompts for duplication and clarity.
7. Commit the prompt library changes.
8. Push to `origin/main` if the workflow requires publishing the update.

Deliverable
- A concise summary of:
  - what prompt gaps were found
  - which new or updated prompts were added
  - why they belong in `generic/` or `trellint/`
  - any prompt ideas that were intentionally rejected

Stopping condition
- The Trellint workspace has been scanned, the prompt library has been updated
  only where justified, and the resulting changes are ready for commit or have
  already been committed and pushed.
