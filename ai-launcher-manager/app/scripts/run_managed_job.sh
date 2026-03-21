#!/usr/bin/env bash

set +e

printf '__AILM_JOB_START__ job_id=%s provider=%s\n' "${AILM_JOB_ID:-unknown}" "${AILM_PROVIDER:-unknown}"
printf '__AILM_COMMAND__ %s\n' "${AILM_JOB_COMMAND:-}"

bash -lc "${AILM_JOB_COMMAND:-}"
status=$?

printf '__AILM_EXIT_CODE__=%s\n' "$status"
exit "$status"
