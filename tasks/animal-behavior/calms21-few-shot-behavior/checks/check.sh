#!/usr/bin/env bash
set -euo pipefail
TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${BPB_CALMS_PYTHON:-python3}" "$TASK_DIR/../_shared/calms_task_score.py" --task "$TASK_DIR" --artifacts "$PWD/artifacts"
