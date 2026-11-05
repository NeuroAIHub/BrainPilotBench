#!/usr/bin/env bash
set -euo pipefail
TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -d "$PWD/data/public" ]; then
  exec "${BPB_CALMS_PYTHON:-python3}" "$TASK_DIR/../_shared/calms_task_reference.py" --task "$TASK_DIR" --public-dir "$PWD/data/public" --output "$PWD/submission"
fi
if [ -d "$PWD/artifacts" ]; then
  exec "${BPB_CALMS_PYTHON:-python3}" "$TASK_DIR/../_shared/calms_task_reference.py" --task "$TASK_DIR" --public-cache --output "$PWD/artifacts/submission"
fi
echo "public data or Oracle artifact directory required" >&2
exit 2
