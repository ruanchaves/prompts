Audit the closed PR #`<number>` as a post-merge review using a coordinator
session plus `tmux` workers running `codex --yolo`. Determine whether it
introduced any critical mistakes that justify reopening the PR, filing a bug
issue, or both.

Inputs
- Repo root: `<repo_path>`
- GitHub repo: `<owner>/<repo>`
- Closed PR number: `<number>`
- Default branch: `<default_branch>`

Worker orchestration
- Keep the current shell as the audit coordinator.
- Start focused tmux audit workers only for independent changed areas:
  - `tmux new-session -d -s audit_<pr>_backend_codex "cd <repo_path> && codex --yolo"`
  - `tmux new-session -d -s audit_<pr>_frontend_codex "cd <repo_path> && codex --yolo"`
  - `tmux new-session -d -s audit_<pr>_tests_codex "cd <repo_path> && codex --yolo"`
- Use only the workers that match the merged surface area.
- Workers should inspect, not edit, unless the coordinator explicitly switches
  into a follow-up fix workflow.

Suggested GitHub commands
```bash
gh pr view <number> --repo <owner>/<repo> --comments
gh pr diff <number> --repo <owner>/<repo>
gh pr checks <number> --repo <owner>/<repo>
gh issue list --repo <owner>/<repo> --search "<number> OR linked:pr"
```

Audit scope
1. Read the PR description, linked issues, review discussion, commits, final
   diff, and merge state.
2. Review CI and test results that were available at merge time.
3. Look for follow-up evidence in the same area when available:
   - hotfix PRs
   - revert commits
   - bug issues
   - subsequent commits touching the same paths
4. Focus only on high-severity problems such as:
   - functional regressions
   - broken edge cases with real user impact
   - data loss or data corruption risks
   - security issues
   - performance regressions
   - API or contract breaks
   - migration or deployment risks
   - missing or misleading tests that allowed a serious bug through

Audit workflow
1. Inspect the merged diff and identify the highest-risk files first.
2. Split independent areas across tmux workers when that reduces review time
   without duplicating effort.
3. Run only the targeted validation needed to confirm or reject the
   highest-risk claims.
4. Correlate any suspected problem with concrete code, tests, behavior, or
   follow-up evidence.
5. Produce a decision-oriented report with findings first.

Output requirements
- For each finding, provide:
  - short title
  - evidence
  - why it is critical
  - whether it warrants `reopening the PR`, `filing a bug`, or `both`
- If no critical issue is found, say so explicitly.
- End with:
  - `Verdict: No action | File bug | Reopen PR and file bug`
  - `Confidence: High | Medium | Low`
  - `Validation: <commands run or not run>`

Rules
- Do not include minor nits, style comments, or speculative concerns without
  evidence.
- Prefer primary evidence from code, tests, runtime behavior, and follow-up
  fixes over guesses.
- If you infer impact from the available evidence, say that it is an inference.
- Do not reopen the PR or file the issue yourself unless explicitly asked to do
  so.
