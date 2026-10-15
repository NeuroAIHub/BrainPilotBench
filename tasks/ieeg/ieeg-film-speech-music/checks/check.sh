#!/usr/bin/env bash
set -euo pipefail

TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${BPB_FILM_EVALUATOR_DATA_ROOT:?Set BPB_FILM_EVALUATOR_DATA_ROOT to the verified owner data root}"
if [[ "${BPB_OFFICIAL_SCORING:-0}" == "1" || -n "${BPB_FILM_OWNER_TEST:-}" ]]; then
  echo "This entry scores public validation only" >&2
  exit 2
fi
exec "${BPB_FILM_PYTHON:-python3}" "$TASK_DIR/checks/run.py" \
  --data-root "$BPB_FILM_EVALUATOR_DATA_ROOT" \
  --submission "$PWD/artifacts/submission" --role validation --bpb-scores
