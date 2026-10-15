#!/usr/bin/env bash
set -euo pipefail
TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${BPB_M1_DATA_DIR:?Set BPB_M1_DATA_DIR to the verified public derived data directory}"
if [[ -n "${BPB_M1_EVALUATOR_DATA_DIR:-}" || -n "${BPB_M1_TEST_MANIFEST:-}" ]]; then
  echo "M1 setup accepts only public Train and Valid data" >&2
  exit 2
fi
exec "${BPB_M1_PYTHON:-python3}" "$TASK_DIR/env/stage_public.py" \
  --source "$BPB_M1_DATA_DIR" --stage-to "${BPB_M1_STAGE_DIR:-$PWD/public_data}"
