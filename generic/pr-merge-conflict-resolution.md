Resolve merge conflicts on a pull request using a coordinator session plus
`tmux` workers running `codex --yolo`. The goal is to produce a clean merge
that preserves the intent of both the PR and the target branch, without
silently dropping behavior from either side.

Inputs
- Repo root: `<repo_path>`
- GitHub repo: `<owner>/<repo>`
- PR number: `<pr_number>`
- Target branch: `<target_branch>`

Worker orchestration
- Keep the current shell as the conflict-resolution coordinator.
- Start tmux workers only when conflicts span independent areas:
  - `tmux new-session -d -s conflict_<pr_number>_area_codex "cd <repo_path> && codex --yolo"`
- Do not create multiple workers that resolve the same file.

Suggested GitHub commands
```bash
gh pr view <pr_number> --repo <owner>/<repo>
gh pr diff <pr_number> --repo <owner>/<repo>
gh pr checks <pr_number> --repo <owner>/<repo>
```

Context gathering
1. Read the PR description, linked issue, and review comments to understand the
   intent of the change.
2. Read the commit log on the PR branch to understand the sequence of changes.
3. Read the recent commit log on the target branch to understand what landed
   since the PR diverged.
4. Identify which commits on each side touch the conflicting files and why.

Resolution workflow
1. Fetch the latest target branch and attempt the merge:
   ```bash
   git fetch origin <target_branch>
   git checkout <pr_branch>
   git merge origin/<target_branch>
   ```
2. List all conflicting files and classify each conflict:
   - **parallel edits** — both sides changed the same region for different
     reasons.
   - **refactor vs. feature** — one side moved or renamed code that the other
     side modified in place.
   - **delete vs. modify** — one side removed code that the other side changed.
   - **dependency or import** — conflicting additions to dependency files, import
     lists, or generated lock files.
3. For each conflicting file:
   a. Read the full file with conflict markers.
   b. Read the file at the merge base, the PR head, and the target head to
      understand each version independently.
   c. Determine which side's intent takes precedence, or whether both intents
      must coexist.
   d. Resolve the conflict so that both intents are preserved unless one side
      explicitly supersedes the other.
   e. If the PR description or reviews indicate that a particular behavior was
      intentionally replaced, respect that — do not resurrect removed code.
4. After resolving all conflicts, stage and commit the merge.

Validation
1. Run the project's test suite. If tests fail:
   - Determine whether the failure is caused by the merge resolution or existed
     prior to it.
   - Fix resolution-caused failures. Do not fix pre-existing failures in this
     branch.
2. Run lint and type checks if the project has them configured.
3. Review the final diff between the merge commit and each parent to confirm no
   unintended deletions or duplications.
4. Push the updated branch and verify CI passes:
   ```bash
   git push origin <pr_branch>
   gh pr checks <pr_number> --repo <owner>/<repo> --watch
   ```

Resolution rules
- Never choose "accept ours" or "accept theirs" on an entire file without
  reading both versions. Blanket strategies discard intent.
- For generated files (lock files, compiled assets), regenerate rather than
  manually merge.
- For dependency files (package.json, requirements.txt, go.mod), merge the
  dependency lists and regenerate the lock file.
- If a conflict is ambiguous and the correct resolution cannot be determined from
  the code, PR description, issue, or reviews, stop and ask the user rather than
  guessing.
- Do not refactor, restyle, or improve code beyond what is needed to resolve the
  conflict.
- The merge commit message should reference the PR number and briefly describe
  the conflict areas resolved.

Coordinator responsibilities
- Monitor tmux workers and prevent overlapping edits to the same file.
- Review the complete merge diff before pushing.
- Confirm CI is green after the push.

Stopping condition
- All conflicts are resolved, the merge commit is pushed, and CI passes on the
  PR branch.
