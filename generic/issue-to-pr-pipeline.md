End-to-end pipeline for issue #<X>. You are the coordinator. You write specs and code yourself, and
delegate reviews to a separate codex process so that the author never reviews their own work.

Repo root: `<repo_path>`

---

## Phase 1 — Spec + Spec Review

### 1a. Write the technical spec (you do this)
Before addressing issue #<X>, write a technical spec as a comment on the issue itself.

Include these sections:
1. **Scope** — files to change (with rationale), files explicitly out of scope (with reason), new files if any.
2. **Plan** — numbered steps, each referencing specific files, ordered so the codebase is never broken between
   steps.
3. **Impact Analysis** — downstream effects and at least two non-obvious edge cases.
4. **Testing Strategy** — existing tests to update, new test cases by name and assertion, end-to-end
   verification method.
5. **Rollback** — simplest revert path; flag anything that complicates a clean rollback.

Rules: keep the spec under 150 lines. If ambiguous, list assumptions explicitly. Do not begin implementation.

### 1b. Dispatch spec review to codex (you launch this)
Once the spec comment is posted, launch a reviewer in a separate process:

```
tmux new-session -d -s spec_review_<X> \
  "cd <repo_path> && codex --yolo 'Review the technical spec posted as a comment on issue #<X>.
Read the issue description and all comments. Identify the spec comment. Evaluate it for:
- Scope completeness (missing files, unjustified exclusions, unnecessary new files)
- Plan ordering (each step must leave codebase buildable, no hidden dependencies)
- Impact Analysis gaps (missing consumers, weak edge cases, concurrency/perf risks)
- Testing coverage (edge cases covered, concrete e2e verification, broken tests acknowledged)
- Rollback realism (unacknowledged migrations, schema changes, API contracts)

Post a single review comment on the issue with this structure:
## Spec Review
### Verdict: APPROVE / REQUEST CHANGES / NEEDS DISCUSSION
### Issues Found
- [ ] **[Section]** Description and suggested fix.
### Suggestions (non-blocking)
### Questions

Be specific — reference exact spec sections. Do not rewrite the spec. If it looks good, approve concisely.'"
```

### 1c. Wait for the spec review
- Poll the issue comments until the spec review appears (check every 30 seconds, timeout after 10 minutes).
- Read the review verdict.

### 1d. Act on the spec review
- **APPROVE** → proceed to Phase 2.
- **REQUEST CHANGES** → revise the spec to address every checked issue in the review. Post the updated spec
  as a new comment (do not edit the original — preserve the review trail). Then re-run step 1b against the
  new spec. Repeat until approved. Maximum 3 revision cycles — if still not approved, stop and escalate to
  the user.
- **NEEDS DISCUSSION** → stop and escalate to the user with a summary of the open questions.

---

## Phase 2 — Implementation + PR Review

### 2a. Implement the approved spec (you do this)
- Create a feature branch `<X>-<short-slug>` from latest main.
- Follow the Plan section exactly, in order.
- After each step, commit with a message referencing the step number and issue
  (e.g., `#<X> step 2: add validation to UserService`).
- Stay within Scope. If a file needs changing but is not in the spec, stop and escalate to the user.
- After all plan steps, execute the Testing Strategy:
  1. Update existing tests identified in the spec.
  2. Write new test cases using the names and assertions from the spec.
  3. Run the full test suite and fix failures introduced by this change.
  4. Perform the end-to-end verification.
- Commit test changes separately.
- Verify each edge case from Impact Analysis is handled.
- Push the branch and open a PR against main. PR body must include:
  - Link to the issue.
  - Link to the approved spec comment.
  - Commit-to-step mapping.
  - Test run results.
  - Any deviations from the spec, with justification.

### 2b. Dispatch PR review to codex (you launch this)
Once the PR is open, launch a reviewer:

```
tmux new-session -d -s pr_review_<X> \
  "cd <repo_path> && codex --yolo 'Review the open PR for issue #<X>.
Read the PR description, diff, all commits, the approved technical spec from the issue comments,
and the issue description.

Check:
1. Spec Compliance — each commit maps to a plan step, only in-scope files touched, deviations justified.
2. Correctness — logic matches spec intent, no off-by-one/null/race bugs, edge cases handled.
3. Testing — all spec test cases present with correct names/assertions, e2e result included.
4. Code Quality — minimal and focused, no unrelated changes, consistent style, no security issues.
5. Rollback Safety — matches spec rollback plan, no unacknowledged irreversible changes.

Post a PR review (APPROVE / REQUEST CHANGES / COMMENT) structured as:
## PR Review — Issue #<X>
### Spec Compliance
### Correctness
### Testing
### Code Quality
### Rollback Safety
### Summary

Review against the spec, not personal preference. Be specific with file and line references.
Approve promptly if clean. Flag critical issues clearly with concrete impact.'"
```

### 2c. Wait for the PR review
- Poll the PR reviews until the codex review appears (check every 30 seconds, timeout after 10 minutes).
- Read the review verdict.

### 2d. Act on the PR review
- **APPROVE** → log the result. Print a summary of what was shipped and confirm the PR is ready for human
  merge. Do not merge automatically.
- **REQUEST CHANGES** → for each issue in the review:
  1. Read the referenced file and line range.
  2. Fix the issue on the feature branch.
  3. Commit with message `#<X> address review: <short description>`.
  - After all fixes, push and re-run step 2b. Maximum 3 fix cycles — if still not approved, stop and
    escalate to the user.
- **COMMENT** → if all comments are non-blocking questions, respond to each on the PR and proceed as if
  approved. If any comment implies a required change, treat it as REQUEST CHANGES.

---

## Guardrails
- Never merge the PR. The pipeline ends with a PR ready for human review and merge.
- Never skip the codex review steps. The author must not review their own work.
- Never edit the original spec comment after a review is posted — always post revisions as new comments.
- If any phase hits its retry limit, stop cleanly and post a summary comment on the issue explaining where
  the pipeline stalled and what needs human attention.
