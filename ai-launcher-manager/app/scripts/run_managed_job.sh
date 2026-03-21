#!/usr/bin/env bash

set +e

printf '__AILM_JOB_START__ job_id=%s provider=%s\n' "${AILM_JOB_ID:-unknown}" "${AILM_PROVIDER:-unknown}"
case "${AILM_PROVIDER:-}" in
  codex)
    if [ "${AILM_PROMPT+x}" = "x" ]; then
      printf '__AILM_PROVIDER_COMMAND__ %s\n' 'codex --yolo <prompt from AILM_PROMPT>'
      codex --yolo "$AILM_PROMPT"
    else
      printf '__AILM_PROVIDER_COMMAND__ %s\n' 'codex --yolo'
      codex --yolo
    fi
    status=$?
    ;;
  claude)
    printf '__AILM_PROVIDER_COMMAND__ %s\n' 'claude --dangerously-skip-permissions'
    claude --dangerously-skip-permissions
    status=$?
    ;;
  *)
    printf '__AILM_PROVIDER_ERROR__ unknown provider: %s\n' "${AILM_PROVIDER:-}"
    status=64
    ;;
esac

printf '__AILM_EXIT_CODE__=%s\n' "$status"
exit "$status"
