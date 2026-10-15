#!/usr/bin/env bash
set -euo pipefail
TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${BPB_BCI_DATA_DIR:?Set BPB_BCI_DATA_DIR to verified public Train/Valid}"
exec "${BPB_BCI_PYTHON:-python3}" "$TASK_DIR/examples/train_reference.py" \
  --public-data "$BPB_BCI_DATA_DIR" --output "$PWD/artifacts"
