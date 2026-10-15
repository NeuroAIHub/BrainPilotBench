#!/usr/bin/env bash
set -euo pipefail
TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${BPB_B1_PYTHON:-python3}" "$TASK_DIR/solution/make_reference.py" \
  --public-data-dir "${BPB_B1_DATA_DIR:-$PWD/public_data}" \
  --artifacts-dir "${BPB_B1_ARTIFACTS_DIR:-$PWD/artifacts}"
