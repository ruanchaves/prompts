You are in the Trellint `chatbot` repo at `/mnt/c/Users/ruan.rodrigues/Documents/GitHub/trellint/chatbot`.

Goal: determine whether the open PR introduces any new evaluation failures compared with `origin/main`.

Constraints:
- Use the repo-local wrappers: `./bin/python`, `./bin/pip`, `./bin/pytest`.
- Do not create a virtualenv.
- Do not disturb the current working tree or overwrite local changes.
- Do not use the current checkout for branch switching. Use temporary git worktrees for isolation.
- Use the same environment for both branches.
- Do not install missing dependencies unless absolutely necessary; if a suite is unavailable because of environment/
tooling, report that explicitly.

AZURE mode policy:
- Execute every suite in AZURE mode whenever that suite supports AZURE execution.
- Export `CHATBOT_SERVICE_MODE=azure` for all suite runs unless a suite is inherently non-AZURE.
- Reuse the existing Azure environment variables if present:
  - `CHATBOT_AZURE_OPENAI_ENDPOINT`
  - `CHATBOT_AZURE_OPENAI_API_KEY`
  - `CHATBOT_AZURE_OPENAI_DEPLOYMENT`
- For `retriever_quality.ragas`, explicitly force Azure/Ragas execution with:
  - `--config force_mode=ragas`
- Do not silently accept a fallback to MOCK mode for suites that should have run in AZURE mode.
- After each run, inspect the run JSON and/or logs to confirm the actual engine/mode used.
- If a suite is AZURE-capable but could not actually run in AZURE mode, report that as an execution issue.
- If a suite is inherently non-AZURE, run it in its supported mode and note that clearly.

Execution plan:
1. Identify the PR head.
   - If I gave you a PR number, resolve it with `gh pr view`.
   - Otherwise assume the current `HEAD` / current branch is the PR branch.
2. Fetch `origin/main`.
3. Create two temporary worktrees:
   - one at `origin/main`
   - one at the PR head
4. In each worktree, enumerate the registered evaluation suites dynamically from the repo code, not by hardcoding:
   - Use `app.services.evaluations.registry.get_evaluation_registry().list_suites()`
   - Record each suite's `key`, `display_name`, `available`, and `availability_reason`
5. Run every registered suite in both worktrees.
   - For each suite, if `available=False`, record it as unavailable with the reason and do not force execution.
   - Otherwise run:
     - default:
       `CHATBOT_SERVICE_MODE=azure ./bin/python scripts/run_evaluation_suite.py --suite-key <suite_key> --secondary-
persistence none --timeout 1800 --output-json <artifact_dir>/<branch>/<suite_key>.json`
     - for `retriever_quality.ragas`:
       `CHATBOT_SERVICE_MODE=azure ./bin/python scripts/run_evaluation_suite.py --suite-key retriever_quality.ragas
--secondary-persistence none --timeout 1800 --config force_mode=ragas --output-json <artifact_dir>/<branch>/
retriever_quality.ragas.json`
   - For suites that do not support AZURE mode, run them in their supported mode and record that explicitly.
   - Capture stdout/stderr for each run into adjacent log files.
6. Compare `origin/main` vs PR results and determine regressions.

Regression rules:
- Count as a PR regression if a suite passes on `origin/main` and fails, errors, cancels, or becomes unavailable on the
PR.
- Count as a PR regression if both runs complete but the PR introduces new failing cases that were not failing on `origin/
main`.
- Count as a PR regression if suite availability regresses on the PR.
- Count as a PR regression if AZURE execution works on `origin/main` but not on the PR for a suite that should run in
AZURE mode.
- Do not count as a PR regression if a suite is unavailable on both branches for the same reason.
- Do not count as a PR regression if a suite already fails on `origin/main` and the PR does not introduce any additional
failing cases.
- Metric deltas without new failures should be reported, but not classified as regressions.

Deliverables:
- A clear verdict: `PR introduces evaluation regressions: yes/no`
- A compact table with:
  `suite | main status | PR status | azure mode confirmed? | regression | notes`
- A separate section for:
  - suites already failing on `origin/main`
  - suites unavailable due to environment/tooling
  - suites that are inherently non-AZURE
  - suites that unexpectedly fell back from AZURE to MOCK/local mode
  - exact artifact paths for the saved JSON and log files
- Include the exact commands you ran.
- Clean up the temporary worktrees before finishing.

Post your deliverables as a comment to the PR on github.

Known suite keys today are:
- `nlu_accuracy.benchmark`
- `conversation_quality.custom_judge`
- `retriever_quality.ragas`
- `conversation_quality.deepeval`
- `adversarial_safety.promptfoo`
- `nlu_accuracy.pytest_legacy`

Do the work end-to-end. Do not stop at a plan.
