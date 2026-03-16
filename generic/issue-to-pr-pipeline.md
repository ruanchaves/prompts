End-to-end pipeline for issue #<X>. You are the coordinator. You write specs and code yourself, and
delegate reviews to a separate codex process so that the author never reviews their own work.

Repo root: `<repo_path>`
Prompt directory: `<prompts_path>` (contains `review-technical-spec.md` and `review-spec-implementation-pr.md`)

---

## Phase 0 — Pre-flight

Before doing any work, validate that the pipeline can proceed:

1. Confirm issue #<X> is open. If it is closed or does not exist, stop immediately.
2. Check that no branch named `<X>-*` already exists and no open PR references issue #<X>. If either exists,
   stop and ask the user whether to continue from existing work or start fresh.
3. Read the issue description. If it lacks enough detail to write a spec (no clear problem statement or
   acceptance criteria), stop and ask the user for clarification rather than guessing.
4. Kill any stale tmux sessions from previous runs: `tmux kill-session -t spec_review_<X> 2>/dev/null;
   tmux kill-session -t pr_review_<X> 2>/dev/null`.

---

## Phase 1 — Spec + Spec Review

### 1a. Write the technical spec (you do this)
Before addressing issue #<X>, write a technical spec as a comment on the issue itself.

Include these sections:
1. **Scope** — files to change (with rationale), files explicitly out of scope (with reason), new files if any.
   For every file listed, verify it actually exists in the repo before including it.
2. **Plan** — numbered steps, each referencing specific files, ordered so the codebase is never broken between
   steps.
3. **Impact Analysis** — downstream effects and at least two non-obvious edge cases.
4. **Testing Strategy** — existing tests to update, new test cases by name and assertion, end-to-end
   verification method.
5. **Rollback** — simplest revert path; flag anything that complicates a clean rollback.
6. **Design Decisions** — for each non-obvious choice in the plan, briefly state what alternatives were
   considered and why they were rejected. This gives the reviewer context to distinguish intentional trade-offs
   from oversights.

Rules: keep the spec under 150 lines. If ambiguous, list assumptions explicitly. Do not begin implementation.

### 1b. Dispatch spec review to codex (you launch this)
Once the spec comment is posted, launch a reviewer in a separate process. Load the review prompt from the
prompt file rather than inlining it, substituting the issue number:

```
tmux kill-session -t spec_review_<X> 2>/dev/null
SPEC_PROMPT=$(sed 's/#<X>/#<ISSUE_NUMBER>/g' <prompts_path>/review-technical-spec.md)
tmux new-session -d -s spec_review_<X> \
  "cd <repo_path> && codex --yolo '$SPEC_PROMPT'"
```

After launching, wait 10 seconds and then verify the tmux session is still running:
`tmux has-session -t spec_review_<X> 2>/dev/null`. If the session died immediately, check for errors and
retry once before escalating to the user.

### 1c. Wait for the spec review
- Poll the issue comments until the spec review appears (check every 30 seconds).
- Read the review verdict.

### 1d. Act on the spec review
- **APPROVE** → proceed to Phase 2.
- **REQUEST CHANGES** → revise the spec to address every checked issue in the review. Post the updated spec
  as a new comment (do not edit the original — preserve the review trail). Before re-running step 1b, include
  in the reviewer prompt: "Also read the prior spec review at <comment_url> and verify that all previously
  flagged issues have been addressed." Track which issues were flagged across cycles — if the same issue
  reappears after being "fixed", stop and escalate to the user immediately rather than burning retries.
  Maximum 3 revision cycles — if still not approved, stop and escalate to the user.
- **NEEDS DISCUSSION** → stop and escalate to the user with a summary of the open questions.

---

## Phase 2 — Implementation + PR Review

### 2a. Pre-implementation smoke test
Before writing any code:
1. Run the existing test suite on main and capture the output as the baseline. Save this to a temporary file
   (`/tmp/baseline_tests_<X>.log`). Any pre-existing failures are not your responsibility — note them for
   later comparison.
2. Verify that every file listed in the spec's Scope section actually exists in the repo. If any are missing,
   stop and flag the discrepancy to the user.

### 2b. Implement the approved spec (you do this)
- Create a feature branch `<X>-<short-slug>` from latest main.
- Follow the Plan section exactly, in order.
- After each step, commit with a message referencing the step number and issue
  (e.g., `#<X> step 2: add validation to UserService`).
- Stay within Scope. If a file needs changing but is not in the spec, stop and escalate to the user.
- After all plan steps, execute the Testing Strategy:
  1. Update existing tests identified in the spec.
  2. Write new test cases using the names and assertions from the spec.
  3. Run the full test suite and fix failures introduced by this change. Compare against the baseline from
     step 2a — only failures that are new relative to the baseline need fixing.
  4. Perform the end-to-end verification.
- Commit test changes separately.
- Verify each edge case from Impact Analysis is handled.

### 2c. Post-implementation verification
Before opening the PR:
1. Count the implementation commits (excluding test commits). This number must match the number of steps in
   the spec's Plan section. If it does not, you either combined or split steps — fix the history to match
   the spec exactly.
2. Rebase the feature branch onto latest main to catch conflicts early. If conflicts arise, resolve them and
   re-run the test suite.

### 2d. Open the PR
- Push the branch and open a PR against main. PR body must include:
  - Link to the issue.
  - Link to the approved spec comment.
  - Commit-to-step mapping.
  - Test run results (and note any pre-existing failures from baseline).
  - Any deviations from the spec, with justification.

### 2e. Dispatch PR review to codex (you launch this)
Once the PR is open, launch a reviewer. Load the review prompt from the prompt file:

```
tmux kill-session -t pr_review_<X> 2>/dev/null
PR_PROMPT=$(sed 's/#<X>/#<ISSUE_NUMBER>/g' <prompts_path>/review-spec-implementation-pr.md)
PR_PROMPT="$PR_PROMPT

Additionally: clone the branch, run the full test suite, and include the actual test results in your review.
Do not rely solely on what the PR description claims — verify it."
tmux new-session -d -s pr_review_<X> \
  "cd <repo_path> && codex --yolo '$PR_PROMPT'"
```

After launching, wait 10 seconds and verify the tmux session is running. If it died, retry once before
escalating.

### 2f. Wait for the PR review
- Poll the PR reviews until the codex review appears (check every 30 seconds).
- Read the review verdict.

### 2g. Act on the PR review
- **APPROVE** → proceed to Phase 3.
- **REQUEST CHANGES** → for each issue in the review:
  1. Read the referenced file and line range.
  2. Assess the fix complexity. If any single fix requires more than 20 changed lines, stop and escalate to
     the user — the fix is too large to self-correct safely without spec backing.
  3. Fix the issue on the feature branch.
  4. Commit with message `#<X> address review: <short description>`.
  - After all fixes, push. Before re-running step 2e, include in the reviewer prompt: "Also read the prior
    PR review and verify that all previously flagged issues have been addressed." Track flagged issues across
    cycles — if the same issue reappears, escalate immediately. Maximum 3 fix cycles — if still not approved,
    stop and escalate to the user.
- **COMMENT** → if all comments are non-blocking questions, respond to each on the PR and proceed as if
  approved. If any comment implies a required change, treat it as REQUEST CHANGES.

---

## Phase 3 — Pipeline Summary

Post a summary comment on the issue that links to every artifact the pipeline produced:

```
## Pipeline Summary — Issue #<X>

### Spec
- Original spec: <comment_url>
- Revisions (if any): <comment_urls>
- Spec review(s): <comment_urls>
- Final verdict: APPROVED (cycle N)

### Implementation
- PR: <pr_url>
- Branch: <branch_name>
- Commits: N implementation + N test + N review fixes
- PR review(s): <review_urls>
- Final verdict: APPROVED (cycle N)

### Status
Ready for human review and merge.
```

Log the result to the console. Do not merge the PR.

---

## Guardrails
- Never merge the PR. The pipeline ends with a PR ready for human review and merge.
- Never skip the codex review steps. The author must not review their own work.
- Never edit the original spec comment after a review is posted — always post revisions as new comments.
- If any phase hits its retry limit, stop cleanly and post a summary comment on the issue explaining where
  the pipeline stalled and what needs human attention.
- If the same review issue reappears across retry cycles (oscillation), escalate immediately rather than
  consuming remaining retries.
- If a review fix requires more than 20 changed lines, escalate to the user rather than self-correcting
  without spec backing.
- Always kill stale tmux sessions before launching new ones for the same issue.
- Always verify tmux sessions are running after launch — do not silently poll for a review that will never
  arrive.
