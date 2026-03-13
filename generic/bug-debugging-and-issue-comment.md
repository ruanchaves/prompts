Investigate open bug issues in this repository using a coordinator session plus
`tmux` workers running `codex --yolo`. The goal is not to guess at fixes. The
goal is to improve observability around a bug, reproduce it if possible, and
leave a high-signal issue comment with concrete debugging findings.

Inputs
- Repo root: `<repo_path>`
- GitHub repo: `<owner>/<repo>`
- Default branch: `<default_branch>`
- Bug issue filter: `<label_or_query>`

Required worker model
- Keep the current shell as coordinator.
- Start a tmux discovery worker:
  - `tmux new-session -d -s bug_scan_codex "cd <repo_path> && codex --yolo"`
- For the selected issue, start focused workers only if the work splits cleanly:
  - `tmux new-session -d -s bug_<number>_debug_codex "cd <repo_path> && codex --yolo"`
  - `tmux new-session -d -s bug_<number>_repro_codex "cd <repo_path> && codex --yolo"`
- Do not create multiple workers that edit the same files.

Issue discovery
1. Scan open issues that are bugs.
2. Prefer explicit bug labels first.
3. If the repo does not use a clean bug label, infer likely bugs from issue
   titles, descriptions, linked PRs, and prior comments.
4. Choose the bug issue with the best signal-to-noise ratio:
   - clear user-visible failure
   - enough context to investigate
   - no active owner already resolving it

Suggested GitHub commands
```bash
gh issue list --repo <owner>/<repo> --state open --label bug
gh issue view <number> --repo <owner>/<repo> --comments
gh issue comment <number> --repo <owner>/<repo> --body-file <comment_file>
```

Investigation workflow
1. Read the issue body, comments, linked PRs, and linked commits.
2. Search the codebase for the affected path, error message, entry point, or
   feature area.
3. Review prior fix attempts before making changes:
   - linked PRs
   - closed PRs referencing the issue
   - commits mentioning the issue number
   - abandoned branches or worktrees if they exist locally
4. For each prior attempt, record:
   - where it happened
   - what it tried to change
   - why it appears to have failed or remained incomplete
5. Improve logging and debugging around the suspected failure path.
6. Attempt to reproduce the bug using the narrowest meaningful command or user
   flow.
7. Capture what the improved logs changed in your understanding.

Logging and debugging rules
- Add focused logs, traces, assertions, counters, or structured context near
  the suspected failure path.
- Prefer logs that expose state transitions, inputs, branch decisions, and
  external dependency outcomes.
- Do not add noisy blanket logging across unrelated modules.
- If the new logging is only temporary and too noisy for the codebase, revert it
  after collecting evidence unless the issue clearly justifies keeping it.
- If you keep the logging, say why it is worth keeping.

Reproduction rules
- Reproduce with the smallest deterministic workflow you can find.
- If you cannot fully reproduce, distinguish between:
  - fully reproduced
  - partially reproduced
  - not reproduced
- When reproduction fails, still report the strongest evidence gained from the
  improved instrumentation.
- Do not claim root cause certainty unless the evidence supports it.

Issue comment requirements
- Post exactly one high-signal comment on the chosen issue.
- The comment must include:
  - current understanding of the bug
  - what logging or debugging was added or used
  - reproduction status and exact steps or commands tried
  - the most likely failure path or root-cause hypothesis
  - prior resolution attempts and where they were unsuccessful
  - next recommended investigation or fix direction
- Be concrete about "where":
  - PR numbers
  - commit SHAs
  - files or modules
  - prior comments or test paths
- Be concrete about "why unsuccessful":
  - wrong code path
  - incomplete coverage
  - issue not reproducible under tested conditions
  - missing instrumentation
  - fix addressed symptoms but not the underlying state transition

Comment template
```text
Investigation update

Current understanding
- ...

Logging and debugging performed
- ...

Reproduction attempt
- Status: reproduced | partially reproduced | not reproduced
- Steps/commands:
  - ...
- Observed evidence:
  - ...

Previous resolution attempts
- <where>: <what was tried>
  Why it appears unsuccessful: <reason>

Likely failure path
- ...

Recommended next step
- ...

- debugging-logging-review-agent
```

Coordinator responsibilities
- Monitor the tmux workers and prevent overlapping edits.
- Review the diff for debug instrumentation before any comment is posted.
- Make sure the final issue comment is evidence-based and signed exactly:
  `- debugging-logging-review-agent`
- If code changes were made only for debugging and are not meant to stay, revert
  them before finishing.

Stopping condition
- One open bug issue has been investigated, the repository has any intended
  debugging changes preserved or reverted appropriately, and the signed issue
  comment has been posted.
