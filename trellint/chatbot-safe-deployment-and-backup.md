Run a safe deployment or backup workflow for Trellint's `chatbot` project using
`tmux` workers running `codex --yolo`. Optimize for volume safety, verified
backups, bounded commands, and explicit rollback posture.

Working directory
- `/mnt/c/Users/ruan.rodrigues/Documents/GitHUb/trellint/chatbot`

Inputs
- Target environment: `<environment>`
- Goal: `<routine_redeploy|single_service_restart|backup_only|restore|postgres_upgrade>`
- Branch or image version: `<branch_or_tag>`
- Risk notes: `<notes>`

Required worker model
- Keep the current shell as coordinator.
- Start only the workers needed for the selected workflow:
  - `tmux new-session -d -s chatbot_deploy_backup_codex "cd /mnt/c/Users/ruan.rodrigues/Documents/GitHUb/trellint/chatbot && codex --yolo"`
  - `tmux new-session -d -s chatbot_deploy_exec_codex "cd /mnt/c/Users/ruan.rodrigues/Documents/GitHUb/trellint/chatbot && codex --yolo"`
  - `tmux new-session -d -s chatbot_deploy_verify_codex "cd /mnt/c/Users/ruan.rodrigues/Documents/GitHUb/trellint/chatbot && codex --yolo"`
- Keep ownership clean:
  - backup worker handles backup commands and artifact verification
  - exec worker handles deployment or restore commands
  - verify worker handles health checks, logs, and rollback readiness

Required prep
- Read:
  - `README.md`
  - `docs/deployment.md`
  - `scripts/pre-deploy-backup.sh`
  - `scripts/restore-from-backup.sh` if the goal includes restore
- Inspect the current `docker compose` state before making changes.

Hard safety rules
- Never run `docker compose down -v` unless the workflow explicitly requires
  destructive volume replacement and you have already verified backups.
- Treat named volumes as persistent state that must be preserved by default.
- Prefer `docker compose down` or `docker compose up --build -d` for routine
  redeployments.
- Before destructive steps, capture the exact backup artifact paths and verify
  they exist.
- If the environment or credentials required for backup upload are missing,
  stop and report it instead of improvising.

Execution workflow
1. Identify which services and volumes are in scope.
2. Confirm the correct branch, image tag, or deployment target.
3. If the goal is not explicitly `backup_only`, create or verify backups first.
4. Prefer the repo script for pre-deploy backups:
   - `./scripts/pre-deploy-backup.sh`
   - optionally `--skip-redis`
   - optionally `--upload-azure`
5. Verify backup artifacts:
   - dump files
   - KB copy
   - Redis snapshot if requested
   - manifest
6. Execute the chosen path:
   - routine redeploy
   - single service rebuild
   - restore from backup
   - PostgreSQL major-version upgrade flow
7. Run post-change verification:
   - `docker compose ps`
   - health endpoint checks
   - bounded log inspection
8. Record rollback posture before declaring success.

Validation and output requirements
- Report:
  - backup artifacts created or reused
  - commands run
  - services restarted or replaced
  - health results
  - rollback entry point if something fails later
- If a restore or destructive volume replacement was performed, say exactly
  which volumes were replaced and which backup source was used.

Stopping condition
- The requested deployment or backup workflow is complete, the resulting state
  has been verified, and the user has a clear record of backup location, health
  status, and rollback posture.
