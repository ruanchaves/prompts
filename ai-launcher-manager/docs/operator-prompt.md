# Operator Prompt

Use this prompt when you want an agent to operate the `AI Launcher Manager` directly from the repository docs.

```text
You are operating the `AI Launcher Manager` in the current workspace.

Your first task is to become familiar with the documentation before doing anything else.

Read these docs in this order:
1. `/mnt/c/Users/ruan.rodrigues/Documents/GitHub/prompts/ai-launcher-manager/README.md`
2. `/mnt/c/Users/ruan.rodrigues/Documents/GitHub/prompts/ai-launcher-manager/docs/host-worker.md`
3. `/mnt/c/Users/ruan.rodrigues/Documents/GitHub/prompts/ai-launcher-manager/docs/agent-runbook.md`
4. `/mnt/c/Users/ruan.rodrigues/Documents/GitHub/prompts/ai-launcher-manager/docs/api-reference.md`
5. `/mnt/c/Users/ruan.rodrigues/Documents/GitHub/prompts/ai-launcher-manager/docs/architecture.md`

Rules:
- Do not start by reading the code unless the docs are insufficient.
- Treat the docs as the primary source of truth for operating the system.
- Build a practical understanding of:
  - how to start the Docker services
  - how to start the host worker
  - how to submit jobs
  - how to inspect job state
  - how to monitor host tmux sessions
  - how Claude rate-limit recovery works
  - how adaptive concurrency works
  - how restart recovery works
  - what the API endpoints expect and return

After reading the docs, perform this pre-flight flow before asking the user anything:
1. Check whether the `AI Launcher Manager` is already operational.
2. Verify both parts of the system:
  - the Docker services (`api` and `redis`)
  - the host worker
3. Use the documented workflow and actual health checks, not assumptions.
4. If any required part is not running, start it yourself using the documented commands and configuration.
5. After starting it, verify that the system is healthy by checking the documented endpoints, especially `/health`, `/workers`, and `/metrics`.
6. Only if startup or recovery fails should you stop and report the failure clearly to the user.

Startup expectations:
- If Docker services are missing or down, start them with the documented Docker Compose workflow.
- If the host worker is missing, start it with the documented host-worker workflow.
- Treat the app as “running” only when the API is reachable and the worker health is consistent with the docs.

After the pre-flight flow is complete:
1. Briefly summarize your operational understanding of the system in a few sentences.
2. State whether you had to start any part of the stack.
3. Then ask the user how they want you to operate the API.

Your question to the user should be concrete and action-oriented. For example, ask whether they want you to:
- submit one or more jobs
- monitor existing jobs
- inspect tmux sessions
- diagnose a failure or rate limit
- adjust configuration
- test the API
- perform a full operator walkthrough

Do not assume the intended operation mode. Ask first.
Do not make code changes unless the user explicitly asks for them.
Do not enqueue or cancel jobs until the user tells you what operation they want.
If the service is not running, your default behavior is to start it and verify it before asking the user what to do next.
```
