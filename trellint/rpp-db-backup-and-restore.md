Run RPP database backup or restore workflows using `tmux` workers running
`codex --yolo`. Optimize for safe database handling, explicit target selection,
and verified export or import artifacts.

Working directory
- `/mnt/c/Users/ruan.rodrigues/Documents/GitHUb/trellint/rpp`

Inputs
- Goal: `<export|import|dry_run>`
- Scope: `<sqlite|postgres|all>`
- Input or output path: `<path>`
- Environment: `<host|docker>`

Required worker model
- Keep the current shell as coordinator.
- Start only the workers needed for the chosen scope:
  - `tmux new-session -d -s rpp_db_plan_codex "cd /mnt/c/Users/ruan.rodrigues/Documents/GitHUb/trellint/rpp && codex --yolo"`
  - `tmux new-session -d -s rpp_db_exec_codex "cd /mnt/c/Users/ruan.rodrigues/Documents/GitHUb/trellint/rpp && codex --yolo"`
  - `tmux new-session -d -s rpp_db_verify_codex "cd /mnt/c/Users/ruan.rodrigues/Documents/GitHUb/trellint/rpp && codex --yolo"`
- Keep ownership clean:
  - plan worker validates environment variables and target database selection
  - exec worker runs `db_backup.py`
  - verify worker confirms output files or import results

Required prep
- Read:
  - `README.md`
  - `docs/guides/db-backup.md`
  - `docs/guides/configuration.md`
  - `scripts/db_backup.py`
- Determine whether the operation should run on the host or inside Docker.

Hard safety rules
- Prefer `--dry-run` first whenever the scope or environment is uncertain.
- Before import, verify the target database URL and confirm which database will
  be overwritten.
- If required CLI tools or connection variables are missing, stop and report the
  exact prerequisite instead of guessing.
- Do not mix SQLite and PostgreSQL targets accidentally; state the selected
  scope clearly before execution.

Execution workflow
1. Identify the target database scope:
   - SQLite user database
   - PostgreSQL metadata database
   - both
2. Confirm the relevant environment variables:
   - `RPP_DATABASE_URL`
   - `RPP_METADATA_DATABASE_URL`
3. Decide whether to run on the host or inside Docker.
4. Start with a dry run when useful:
   - `python scripts/db_backup.py export --output ./backups/ --dry-run`
   - `python scripts/db_backup.py import --input ./backups/ --dry-run`
5. Run the selected operation with the narrowest scope needed.
6. If exporting:
   - verify files exist
   - verify timestamps and compression state
7. If importing:
   - verify the source files used
   - verify the target connection
   - perform a minimal post-import sanity check

Validation and output requirements
- Report:
  - goal and scope
  - environment used
  - command lines run
  - files created or consumed
  - whether compression was used
  - any blocked prerequisites
- If importing, report the exact database target and sanity checks performed.

Stopping condition
- The requested export, import, or dry-run workflow is complete, and the user
  has a clear record of the scope, commands, artifacts, and verification
  results.
