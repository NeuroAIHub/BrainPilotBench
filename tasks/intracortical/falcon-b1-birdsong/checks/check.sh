#!/usr/bin/env bash
set -euo pipefail
TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${BPB_B1_DATA_DIR:?Set BPB_B1_DATA_DIR to staged public B1 data}"
if [[ "${BPB_OFFICIAL_SCORING:-0}" == "1" || -n "${BPB_B1_EVALUATOR_DATA_DIR:-}" || -n "${BPB_B1_TEST_MANIFEST:-}" ]]; then
  echo "This check scores public Valid only" >&2
  exit 2
fi
exec "${BPB_B1_PYTHON:-python3}" "$TASK_DIR/checks/score.py" \
  --task "$TASK_DIR" --artifacts "$PWD/artifacts" \
  --data-manifest "$BPB_B1_DATA_DIR/valid/manifest.json"
