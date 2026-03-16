Before addressing issue #<X>, you must write a technical spec as a comment on the issue itself.

  ## Required Sections

  ### 1. Scope
  - **Files to change:** List each file with a one-line rationale for why it needs modification.
  - **Files explicitly out of scope:** List files that a reviewer might expect to see changed, and explain why
  they will not be touched.
  - **New files (if any):** List any files to be created, with justification for why an existing file cannot be
  extended instead.

  ### 2. Plan
  - Numbered step-by-step implementation order.
  - Each step must reference the specific file(s) it touches.
  - Steps must be ordered so that the codebase is never left in a broken state between steps (i.e., each step
  could be a valid commit).

  ### 3. Impact Analysis
  - **Downstream effects:** What existing behavior, tests, or integrations could break?
  - **Edge cases:** List at least two non-obvious scenarios this change must handle correctly.

  ### 4. Testing Strategy
  - Which existing tests need to be updated?
  - What new test cases are required? Describe each by name and what it asserts.
  - How will you verify the fix end-to-end (not just unit tests)?

  ### 5. Rollback
  - If this change causes a regression, what is the simplest way to revert it? Flag anything that makes a clean
  revert difficult (migrations, schema changes, external API contracts).

  ## Rules
  - Do NOT begin implementation until the spec is posted and the user has approved it.
  - If the issue is ambiguous, list your assumptions explicitly in the spec rather than guessing silently.
  - Keep the entire spec under 150 lines. If you need more, the scope is too large — propose splitting the issue
   first
