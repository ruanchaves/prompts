You are in the Trellint `chatbot` repo at `/mnt/c/Users/ruan.rodrigues/Documents/GitHub/trellint/chatbot`.

Goal: determine whether the open PR introduces any new evaluation failures compared with `origin/main`.

Constraints:
- Do not disturb the current working tree or overwrite local changes.
- Do not use the current checkout for branch switching.
- Use Docker containers for all evaluation runs — this provides Postgres, Redis, and all
  service dependencies out of the box.
- Do not install missing dependencies on the host; if a suite is unavailable inside the
  container because of environment/tooling, report that explicitly.

AZURE mode policy:
- Execute every suite in AZURE mode whenever that suite supports AZURE execution.
- Pass `CHATBOT_SERVICE_MODE=azure` to the container for all suite runs unless a suite is inherently non-AZURE.
- Forward the existing Azure environment variables from the host `.env` / shell into the container:
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

2. Prepare two source trees (choose the lightest-weight isolation that works):
   - Create two temporary git worktrees under `/tmp`:
     - one at `origin/main`  (e.g. `/tmp/eval-<PR>-main`)
     - one at the PR head     (e.g. `/tmp/eval-<PR>-pr`)
   - These worktrees are only used as Docker build contexts; no host-side Python execution is needed.

3. For **each** worktree, build and start a Docker Compose stack:
   ```bash
   # Example for the main branch worktree:
   cd /tmp/eval-<PR>-main/chatbot
   docker compose -p eval-<PR>-main up -d --build chatbot-api chatbot-db redis langfuse langfuse-db
   ```
   - Use distinct Compose project names (`-p eval-<PR>-main`, `-p eval-<PR>-pr`) so both
     stacks run concurrently without port/name collisions.
   - Override host port mappings to avoid conflicts (e.g. `--scale` or env-var overrides).
   - Wait for the `chatbot-api` health check to pass before proceeding.

4. Inside each running `chatbot-api` container, enumerate the registered evaluation suites
   dynamically from the repo code, not by hardcoding:
   ```bash
   docker compose -p eval-<PR>-main exec chatbot-api \
     python -c "from app.services.evaluations.registry import get_evaluation_registry; \
                import json; print(json.dumps(get_evaluation_registry().list_suites(), default=str))"
   ```
   - Record each suite's `key`, `display_name`, `available`, and `availability_reason`.

5. Run every registered suite in both containers.
   - For each suite, if `available=False`, record it as unavailable with the reason and do not force execution.
   - Otherwise `docker compose exec` into the container:
     - default:
       ```bash
       docker compose -p eval-<PR>-main exec \
         -e CHATBOT_SERVICE_MODE=azure \
         -e CHATBOT_AZURE_OPENAI_ENDPOINT \
         -e CHATBOT_AZURE_OPENAI_API_KEY \
         -e CHATBOT_AZURE_OPENAI_DEPLOYMENT \
         chatbot-api \
         python scripts/run_evaluation_suite.py \
           --suite-key <suite_key> \
           --secondary-persistence none \
           --timeout 1800 \
           --output-json /tmp/<suite_key>.json
       ```
     - for `retriever_quality.ragas`, add `--config force_mode=ragas`.
   - After each run, `docker compose cp` the result JSON and log out of the container
     into a host-side artifact directory (e.g. `/tmp/eval-<PR>-artifacts/<branch>/`).
   - For suites that do not support AZURE mode, run them in their supported mode and record that explicitly.
   - Capture stdout/stderr for each run into adjacent log files.

6. Compare `origin/main` vs PR results and determine regressions.

7. Tear down both Docker Compose stacks and remove the temporary worktrees:
   ```bash
   docker compose -p eval-<PR>-main down -v --remove-orphans
   docker compose -p eval-<PR>-pr   down -v --remove-orphans
   ```

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
- Clean up Docker stacks and temporary worktrees before finishing.

Post your deliverables as a comment to the PR on github.

Known suite keys today are:
- `nlu_accuracy.benchmark`
- `conversation_quality.custom_judge`
- `retriever_quality.ragas`
- `conversation_quality.deepeval`
- `adversarial_safety.promptfoo`
- `nlu_accuracy.pytest_legacy`

Do the work end-to-end. Do not stop at a plan.
