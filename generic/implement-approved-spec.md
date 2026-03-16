Implement the approved technical spec for issue #<X>.

## Setup
- Read the technical spec from the most recent spec comment on the issue.
- Confirm the spec has been approved before proceeding. If there is no approval or the spec has unresolved
  questions, stop and ask the user.
- Create a feature branch named `<X>-<short-slug>` from the latest main.

## Execution
- Follow the **Plan** section of the spec exactly, in the numbered order given.
- Complete each step fully before moving to the next.
- After each step, make a single commit whose message references the step number and the issue
  (e.g., `#<X> step 2: add validation to UserService`).
- Do not combine steps into a single commit and do not reorder them — the spec was designed so that each step
  leaves the codebase in a valid state.
- Stay within the **Scope** section. Do not touch files listed as out of scope. If you discover a file that
  needs changing but is not in the spec, stop and flag it to the user rather than editing it.

## Testing
- After all plan steps are complete, execute the **Testing Strategy** from the spec:
  1. Update existing tests that the spec identified.
  2. Write the new test cases described in the spec, using the names and assertions specified.
  3. Run the full test suite and fix any failures introduced by this change.
  4. Perform the end-to-end verification described in the spec.
- Commit test changes separately from implementation commits.

## Edge Cases
- Revisit the **Edge cases** listed in the Impact Analysis section. For each one, verify that the
  implementation handles it correctly. If it does not, fix it before proceeding.

## Pull Request
- Push the branch and open a PR against main.
- PR title: short description referencing the issue number.
- PR body must include:
  - A link to the issue.
  - A link to the approved spec comment.
  - A summary of what was implemented, mapping each commit to its spec step.
  - The results of the test run.
  - Any deviations from the spec, with justification.

## Rules
- If anything in the spec is ambiguous or appears incorrect during implementation, stop and ask — do not
  guess or deviate silently.
- Do not refactor, optimize, or improve code outside the spec scope.
- If tests fail for reasons unrelated to this change, note them in the PR but do not fix them in this branch.
