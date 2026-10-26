#!/usr/bin/env bash
set -euo pipefail
TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -d "$PWD/data" ]; then
  exec "${BPB_MABE_PYTHON:-python3}" "$TASK_DIR/../_shared/mabe_task_reference.py" --task "$TASK_DIR" --public-dir "$PWD/data" --output "$PWD/submission"
fi
if [ -d "$PWD/artifacts" ]; then
  exec "${BPB_MABE_PYTHON:-python3}" "$TASK_DIR/../_shared/mabe_task_reference.py" --task "$TASK_DIR" --public-cache --output "$PWD/artifacts/submission"
fi
echo "expected a prepared data/ workspace or an artifacts/ validation bundle" >&2
exit 2
