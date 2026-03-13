Run Trellint `chatbot` evaluation workflows using `tmux` workers running
`codex --yolo`. Optimize for dataset integrity, bounded evaluation runs, and a
clear diagnosis of any failing workflows.

Working directory
- `/mnt/c/Users/ruan.rodrigues/Documents/GitHUb/trellint/chatbot`

Inputs
- Goal: `<dry_run|full_evaluation|threshold_tuning|failure_analysis>`
- Dataset path: `<dataset_path_or_default>`
- Threshold overrides: `<optional_overrides>`
- MLflow logging: `<enabled_or_disabled>`

Required worker model
- Keep the current shell as coordinator.
- Start only the workers needed for the chosen scope:
  - `tmux new-session -d -s chatbot_eval_dataset_codex "cd /mnt/c/Users/ruan.rodrigues/Documents/GitHUb/trellint/chatbot && codex --yolo"`
  - `tmux new-session -d -s chatbot_eval_run_codex "cd /mnt/c/Users/ruan.rodrigues/Documents/GitHUb/trellint/chatbot && codex --yolo"`
  - `tmux new-session -d -s chatbot_eval_analysis_codex "cd /mnt/c/Users/ruan.rodrigues/Documents/GitHUb/trellint/chatbot && codex --yolo"`
- Keep ownership clean:
  - dataset worker audits workflow coverage and dataset integrity
  - run worker executes the evaluation commands
  - analysis worker inspects failed conversations and likely causes

Repo-specific rules
- Respect `AGENTS.md`.
- Use the repo-local wrappers:
  - `./bin/python`
  - `./bin/pip`
  - `./bin/pytest`
- Do not create a local `.venv`.
- If `./bin/python` fails because the shared environment is missing, stop and
  report it.

Required prep
- Read:
  - `AGENTS.md`
  - `docs/guides/llm_evaluation_guide.md`
  - `scripts/run_evaluation.py`
  - `docs/reference/conversational_workflows.md` if dataset changes are in scope
- Confirm the Azure OpenAI environment variables required by the evaluation
  guide before attempting a non-dry-run execution.

Execution workflow
1. Determine whether the task is dataset validation, a full judge run, failure
   triage, or threshold tuning.
2. If the task touches the golden dataset, verify it still mirrors
   `docs/reference/conversational_workflows.md` instead of inventing new
   scenarios ad hoc.
3. Start with a dry run:
   - `timeout 120 ./bin/python scripts/run_evaluation.py --dry-run`
4. If a real run is required and credentials are present, execute a bounded run:
   - `timeout 1200 ./bin/python scripts/run_evaluation.py`
   - add `--log-to-mlflow` only when requested or useful
   - add threshold overrides only when justified
5. If the run fails, analyze:
   - which workflows failed
   - whether the failure is data, prompt, retrieval, safety, or environment
     related
   - whether the threshold is wrong or the behavior is wrong
6. Summarize the exact next action:
   - fix dataset
   - fix behavior
   - adjust thresholds
   - rerun with better instrumentation

Validation and output requirements
- Report:
  - command lines used
  - dataset path
  - thresholds used
  - whether MLflow logging was enabled
  - pass/fail summary
  - failed workflow IDs if any
  - likely regression category for each failure cluster

Stopping condition
- The requested evaluation workflow has been completed or cleanly blocked, and
  the user has a clear summary of dataset validity, run outcome, and next steps
  for any failures.
