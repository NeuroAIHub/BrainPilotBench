#!/usr/bin/env bash
set -euo pipefail
TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${BPB_OFFICIAL_SCORING:-0}" == "1" || -n "${BPB_BCI_TEST_MANIFEST:-}" || -n "${BPB_BCI_LABELS_ZIP:-}" ]]; then
  echo "The public CLI scores Valid only. Owner Test uses the separate evaluate.py entry." >&2
  exit 2
fi
: "${BPB_BCI_DATA_DIR:?Set BPB_BCI_DATA_DIR to the public Train/Valid root}"
exec "${BPB_BCI_PYTHON:-python3}" "$TASK_DIR/checks/evaluate.py" \
  --artifacts "$PWD/artifacts" --data "$BPB_BCI_DATA_DIR/valid"
