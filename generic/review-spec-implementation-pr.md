Review the open PR for issue #<X>. Your goal is to verify that the implementation matches the approved
technical spec and meets the project's quality bar.

## Setup
- Read the PR description, diff, and all commits.
- Read the approved technical spec from the issue comments.
- Read the issue description for original context.

## Review Checklist

### 1. Spec Compliance
- Does each commit map to a step in the spec's Plan section? Flag any step that is missing, reordered,
  or combined with another.
- Are all files listed in the Scope section touched, and only those files? Flag any file changed that was
  listed as out of scope or not mentioned at all.
- If the PR notes deviations from the spec, are the justifications reasonable?

### 2. Correctness
- Read the diff carefully. For each changed file:
  - Does the logic match the intent described in the spec?
  - Are there off-by-one errors, null/undefined risks, or unhandled error paths?
  - Are race conditions or concurrency issues possible?
- Verify that the edge cases from the spec's Impact Analysis are actually handled in the code.

### 3. Testing
- Are all test cases described in the spec present in the PR?
- Do the test names and assertions match what the spec specified?
- Are the tests actually testing the right thing, or are they tautological / testing mocks?
- Does the PR include the end-to-end verification result described in the spec?

### 4. Code Quality
- Is the change minimal and focused, or does it include unrelated refactoring or cleanup?
- Are there new dependencies introduced that the spec did not mention?
- Is the code consistent with the surrounding style and conventions?
- Are there any security concerns (injection, auth bypass, data exposure)?

### 5. Rollback Safety
- Does the implementation match the rollback plan in the spec?
- Are there any changes that would make a revert difficult (irreversible migrations, breaking API contracts,
  persisted state format changes) that were not flagged in the spec?

## Output Format
Post a PR review using GitHub's review mechanism with one of:
- **APPROVE** — if the implementation faithfully follows the spec and passes all checks.
- **REQUEST CHANGES** — if there are issues that must be fixed before merge.
- **COMMENT** — if there are only questions or non-blocking suggestions.

Structure the review body as:

```
## PR Review — Issue #<X>

### Spec Compliance
- [x] All plan steps accounted for
- [ ] Issue: step 3 and 4 were combined into one commit — should be split per spec.

### Correctness
- Findings, if any.

### Testing
- Findings, if any.

### Code Quality
- Findings, if any.

### Rollback Safety
- Findings, if any.

### Summary
One-paragraph overall assessment.
```

## Rules
- Review against the spec, not your personal preferences. If the spec was approved, the design decisions in
  it are settled — only flag implementation errors, not design disagreements.
- Be specific. Every comment must reference a file and line range.
- If the PR is clean and matches the spec, approve it promptly — do not block on stylistic nitpicks.
- If you find a critical issue (security, data loss, spec violation), mark it clearly and explain the
  impact concretely.
