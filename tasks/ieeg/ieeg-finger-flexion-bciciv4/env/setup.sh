#!/usr/bin/env bash
set -euo pipefail
TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${1:-}" == "--role" && "${2:-}" != "agent" ]]; then
  echo "BCI setup exposes public Train/Valid only." >&2
  exit 2
fi
if [[ -n "${BPB_BCI_TEST_MANIFEST:-}" || -n "${BPB_BCI_LABELS_ZIP:-}" ]]; then
  echo "Remove evaluator-only Test variables before Agent setup." >&2
  exit 2
fi
: "${BPB_BCI_DATA_DIR:?Set BPB_BCI_DATA_DIR to the verified public Train/Valid root}"
exec "${BPB_BCI_PYTHON:-python3}" "$TASK_DIR/env/stage_public.py" \
  --source "$BPB_BCI_DATA_DIR" --stage-to "${BPB_BCI_STAGE_DIR:-$PWD/public_data}"
