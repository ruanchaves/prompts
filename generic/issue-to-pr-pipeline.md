End-to-end pipeline for issue #<X>. You are the coordinator. You write specs and code yourself.
Spec review and PR review are handled by a separate workflow — do not perform them here.

Repo root: `<repo_path>`
Python virtual environment: `~/envs/trellint` (activate with `source ~/envs/trellint/bin/activate`)

---

## Phase 0 — Pre-flight

Before doing any work, validate that the pipeline can proceed:

1. Confirm issue #<X> is open. If it is closed or does not exist, stop immediately.
2. Check that no branch named `<X>-*` already exists and no open PR references issue #<X>. If either exists,
   stop and ask the user whether to continue from existing work or start fresh.
3. Read the issue description. If it lacks enough detail to write a spec (no clear problem statement or
   acceptance criteria), stop and ask the user for clarification rather than guessing.

---

## Phase 1 — Spec

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

After posting the spec, proceed directly to Phase 2.

---

## Phase 2 — Implementation

### 2a. Pre-implementation smoke test
Before writing any code:
1. Run **only the test files directly related to the files in scope** on main and capture the output as the
   baseline. Save this to a temporary file (`/tmp/baseline_tests_<X>.log`). Any pre-existing failures are not
   your responsibility — note them for later comparison.
   **Do NOT run the full test suite.** The full suite can take tens of minutes and will stall the pipeline.
   Identify the relevant test files from the spec's Scope and Testing Strategy sections and run only those.
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
  3. Run the same targeted test files from the baseline (step 2a) and fix failures introduced by this change.
     Compare against the baseline — only failures that are new relative to the baseline need fixing.
     **Never run the full test suite** — it is too slow and will cause the pipeline to hang.
  4. Perform the end-to-end verification.
- Commit test changes separately.
- Verify each edge case from Impact Analysis is handled.

### 2c. Post-implementation verification
Before opening the PR:
1. Count the implementation commits (excluding test commits). This number must match the number of steps in
   the spec's Plan section. If it does not, you either combined or split steps — fix the history to match
   the spec exactly.
2. Rebase the feature branch onto latest main to catch conflicts early. If conflicts arise, resolve them and
   re-run the targeted tests from step 2a (never the full suite).

### 2d. Open the PR
- Push the branch and open a PR against main. PR body must include:
  - Link to the issue.
  - Link to the spec comment.
  - Commit-to-step mapping.
  - Test run results (and note any pre-existing failures from baseline).
  - Any deviations from the spec, with justification.

---

## Phase 3 — Pipeline Summary

Post a summary comment on the issue that links to every artifact the pipeline produced:

```
## Pipeline Summary — Issue #<X>

### Spec
- Spec: <comment_url>

### Implementation
- PR: <pr_url>
- Branch: <branch_name>
- Commits: N implementation + N test

### Status
Ready for review and merge.
```

Log the result to the console. Do not merge the PR.

---

## Guardrails
- Never merge the PR. The pipeline ends with a PR ready for human review and merge.
- Never edit the original spec comment after it is posted — always post revisions as new comments.
- If any phase fails, stop cleanly and post a summary comment on the issue explaining where
  the pipeline stalled and what needs human attention.
