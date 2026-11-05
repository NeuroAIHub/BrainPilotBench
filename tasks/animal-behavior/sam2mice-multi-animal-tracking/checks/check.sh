#!/usr/bin/env bash
set -euo pipefail
TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${BPB_SAM2MICE_PYTHON:-python3}" "$TASK_DIR/../_sam2mice_tracking/score_task.py" --task "$TASK_DIR" --artifacts "$PWD/artifacts" --public
