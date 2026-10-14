#!/bin/bash
# Trusted parent scorer. Submitted inference runs only inside an isolated container.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
private_dir="${BPB_BRAIN_AGE_EVALUATOR_DIR:-}"
score_dir="${BPB_BRAIN_AGE_SCORE_DIR:-}"
image="${BPB_INFERENCE_IMAGE:-}"
python_bin="${BPB_BRAIN_AGE_PYTHON:-python3}"

if [ -z "$private_dir" ] || [ -z "$score_dir" ]; then
  echo "brain-age scorer requires BPB_BRAIN_AGE_EVALUATOR_DIR and BPB_BRAIN_AGE_SCORE_DIR" >&2
  exit 1
fi
if [[ ! "$image" =~ @sha256:[0-9a-fA-F]{64}$ ]]; then
  echo "brain-age official scorer requires BPB_INFERENCE_IMAGE pinned by immutable digest" >&2
  exit 1
fi

exec "$python_bin" "$script_dir/evaluate_external.py" \
  --submission-dir "$PWD" \
  --evaluator-data "$private_dir" \
  --output-dir "$score_dir" \
  --image "$image" \
  --official --gpus none --cpus 2 --memory 8g --timeout-seconds 1800 \
  --bpb-sentinel
