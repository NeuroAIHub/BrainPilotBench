#!/usr/bin/env bash
set -euo pipefail
TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${BPB_M1_DATA_DIR:?Set BPB_M1_DATA_DIR to the public M1 data directory}"
if [[ "${BPB_OFFICIAL_SCORING:-0}" == "1" || -n "${BPB_M1_EVALUATOR_DATA_DIR:-}" || -n "${BPB_M1_TEST_MANIFEST:-}" ]]; then
  echo "This check scores public Valid only; owner Test requires score.py --role test --owner-test --frozen-artifact-manifest." >&2
  exit 2
fi
exec "${BPB_M1_PYTHON:-python3}" "$TASK_DIR/checks/score.py" \
  --task "$TASK_DIR" --artifacts "$PWD/artifacts" \
  --data-manifest "$BPB_M1_DATA_DIR/valid/manifest.json"
