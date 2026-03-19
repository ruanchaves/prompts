You are in the Trellint `chatbot` repo at `/mnt/c/Users/ruan.rodrigues/Documents/GitHub/trellint/chatbot`.

Goal: run the full evaluation suite against `origin/main` and report the status of every suite.

Constraints:
- Do not disturb the current working tree or overwrite local changes.
- Do not use the current checkout for branch switching.
- The Docker Compose stack is assumed to be already running. Do not build or start containers yourself.
- Do not install missing dependencies on the host; if a suite is unavailable inside the
  container because of environment/tooling, report that explicitly.

Pre-flight check:
- Before doing anything else, verify the required containers are up and healthy:
  ```bash
  docker compose exec chatbot-api echo "ok"
  ```
- If the container is not running or unhealthy, **stop and ask the user to spin up the
  Docker Compose stack** before retrying. Do not attempt to start it yourself.

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
1. Run the pre-flight check described above. Stop if it fails.

2. Inside the running `chatbot-api` container, enumerate the registered evaluation suites
   dynamically from the repo code, not by hardcoding:
   ```bash
   docker compose exec chatbot-api \
     python -c "from app.services.evaluations.registry import get_evaluation_registry; \
                import json; print(json.dumps(get_evaluation_registry().list_suites(), default=str))"
   ```
   - Record each suite's `key`, `display_name`, `available`, and `availability_reason`.

3. Run every registered suite.
   - For each suite, if `available=False`, record it as unavailable with the reason and do not force execution.
   - Otherwise `docker compose exec` into the container:
     - default:
       ```bash
       docker compose exec \
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
     into a host-side artifact directory (e.g. `/tmp/eval-main-artifacts/`).
   - For suites that do not support AZURE mode, run them in their supported mode and record that explicitly.
   - Capture stdout/stderr for each run into adjacent log files.

Deliverables:
- A compact table with:
  `suite | status | azure mode confirmed? | notes`
- A separate section for:
  - suites that failed or errored
  - suites unavailable due to environment/tooling
  - suites that are inherently non-AZURE
  - suites that unexpectedly fell back from AZURE to MOCK/local mode
  - exact artifact paths for the saved JSON and log files
- Include the exact commands you ran.

Known suite keys today are:
- `nlu_accuracy.benchmark`
- `conversation_quality.custom_judge`
- `retriever_quality.ragas`
- `conversation_quality.deepeval`
- `adversarial_safety.promptfoo`
- `nlu_accuracy.pytest_legacy`

Do the work end-to-end. Do not stop at a plan.
