#!/usr/bin/env bash
set -euo pipefail

TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${BPB_M2_PYTHON:-python3}"
PUBLIC_DATA_DIR="${BPB_M2_DATA_DIR:-$PWD/public_data}"
ARTIFACTS_DIR="${BPB_M2_ARTIFACTS_DIR:-$PWD/artifacts}"
exec "$PYTHON_BIN" "$TASK_DIR/solution/make_reference.py" \
  --public-data-dir "$PUBLIC_DATA_DIR" --artifacts-dir "$ARTIFACTS_DIR"
