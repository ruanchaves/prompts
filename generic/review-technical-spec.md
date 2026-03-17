Review the technical spec posted as a comment on issue #<X>. Your goal is to catch gaps, risks, and
ambiguities before implementation begins.

## Process
- Read the issue description and all comments to understand the full context.
- Identify the spec comment (the one following the required spec format with Scope, Plan, Impact Analysis,
  Testing Strategy, and Rollback sections).
- Evaluate the spec against the criteria below.
- Print your review to stdout. Do NOT post comments or interact with GitHub in any way.

## Evaluation Criteria

### Scope
- Are all files that need changing actually listed? Cross-reference the issue description and codebase to check
  for missing files.
- Are the out-of-scope exclusions justified, or is the spec avoiding necessary work?
- If new files are proposed, is there genuinely no existing file that could be extended instead?

### Plan
- Are the steps ordered so that each one leaves the codebase in a valid, buildable state?
- Are there implicit dependencies between steps that are not acknowledged?
- Could any steps be split further to reduce risk, or merged because they are trivially coupled?
- Does every step reference specific files? Flag any step that is vague about what it touches.

### Impact Analysis
- Are the downstream effects complete? Check for missing consumers, callers, or integrations that the spec
  does not mention.
- Are the edge cases genuinely non-obvious, or are they restating the happy path? Suggest better edge cases
  if needed.
- Are there concurrency, performance, or data-integrity risks that the spec ignores?

### Testing Strategy
- Do the proposed test cases actually cover the edge cases listed in Impact Analysis? Flag any gaps.
- Is the end-to-end verification concrete enough to execute, or is it hand-wavy?
- Are there existing tests that will break but are not mentioned?

### Rollback
- Is the rollback plan realistic? Flag anything that makes a clean revert difficult but is not acknowledged
  (migrations, schema changes, external API contracts, feature flags).

## Output Format
Print your review to stdout using the following structure (do NOT post to GitHub):

```
## Spec Review

### Verdict: APPROVE / REQUEST CHANGES / NEEDS DISCUSSION

### Issues Found
- [ ] **[Section]** Description of the issue and suggested fix.

### Suggestions (non-blocking)
- Description of optional improvement.

### Questions
- Anything ambiguous that the spec author should clarify before implementation begins.
```

## Rules
- Be specific. Every issue must reference the exact section and line of the spec it applies to.
- Do not rewrite the spec yourself. Point out what needs to change and let the author revise it.
- If the spec looks good, say so concisely — do not invent issues to appear thorough.
- If the scope is too large for a single spec (over 150 lines or touching more than one logical change),
  recommend splitting the issue before approving.
