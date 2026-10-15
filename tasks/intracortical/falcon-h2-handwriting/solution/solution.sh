#!/usr/bin/env bash
set -euo pipefail
TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${BPB_H2_PYTHON:-python3}" "$TASK_DIR/solution/make_reference.py" \
  --public-data-dir "${BPB_H2_DATA_DIR:-$PWD/public_data}" \
  --artifacts-dir "${BPB_H2_ARTIFACTS_DIR:-$PWD/artifacts}"
