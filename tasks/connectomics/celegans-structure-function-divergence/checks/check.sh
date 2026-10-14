#!/bin/bash
# Trusted scorer entry. Submitted Python is executed only by the restricted
# Docker worker started by evaluate_external.py; this process retains truth.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARTS="./artifacts"
for f in report.md divergence/divergence_analysis.py divergence/contract.json; do
  if [ ! -f "$ARTS/$f" ] || [ -L "$ARTS/$f" ]; then
    echo "missing or unsafe required artifact: $f" >&2
    exit 1
  fi
done

PY="${BPB_PYTHON:-python3}"
PRIV="${BPB_PRIVATE_EVAL_DIR:-}"
IMAGE="${BPB_INFERENCE_IMAGE:-${BPB_CELEGANS_WORKER_IMAGE:-}}"
if [ -z "$PRIV" ] || [ ! -d "$PRIV" ]; then
  echo "private eval data not found in BPB_PRIVATE_EVAL_DIR" >&2
  exit 1
fi
if [ -z "$IMAGE" ]; then
  echo "Docker worker image not configured (BPB_INFERENCE_IMAGE)" >&2
  exit 1
fi
export PYTHONDONTWRITEBYTECODE=1
exec "$PY" "$HERE/evaluate_external.py" --artifacts "$ARTS" --private "$PRIV" --worker-image "$IMAGE"
