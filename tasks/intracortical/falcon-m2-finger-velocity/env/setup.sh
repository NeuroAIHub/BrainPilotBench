#!/usr/bin/env bash
set -euo pipefail
TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${BPB_M2_DATA_DIR:=${BPB_PUBLIC_DATA_ROOT:-}}"
BPB_M2_DATA_DIR="${BPB_PUBLIC_DATA_ROOT:-$BPB_M2_DATA_DIR}"
: "${BPB_M2_DATA_DIR:?Set BPB_M2_DATA_DIR or BPB_PUBLIC_DATA_ROOT to the verified public derived data directory}"
if [[ -n "${BPB_M2_EVALUATOR_DATA_DIR:-}" || -n "${BPB_M2_TEST_MANIFEST:-}" ]]; then
  echo "M2 setup accepts only public Train and Valid data" >&2
  exit 2
fi
exec "${BPB_M2_PYTHON:-python3}" "$TASK_DIR/env/stage_public.py" \
  --source "$BPB_M2_DATA_DIR" --stage-to "${BPB_M2_STAGE_DIR:-$PWD/public_data}"
