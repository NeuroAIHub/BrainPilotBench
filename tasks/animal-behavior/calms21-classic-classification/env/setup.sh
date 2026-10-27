#!/usr/bin/env bash
set -euo pipefail
TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ "${1:-}" = "--role" ]; then
  case "${2:-}" in agent) ;; *) echo "public setup requires agent role" >&2; exit 2;; esac
fi
exec "${BPB_CALMS_PYTHON:-python3}" "$TASK_DIR/../_shared/calms_task_prepare.py" --task "$TASK_DIR" --output "$PWD/data"
