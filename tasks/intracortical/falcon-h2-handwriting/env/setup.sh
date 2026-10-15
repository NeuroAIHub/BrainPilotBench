#!/usr/bin/env bash
set -euo pipefail
TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHARED="$TASK_DIR/../_sequence_shared"
PYTHON_BIN="${BPB_H2_PYTHON:-python3}"
if [[ "${1:-}" == "--role" && "${2:-}" != "agent" ]]; then
  echo "H2 setup prepares Train and Valid only" >&2
  exit 2
fi
if [[ -n "${BPB_H2_EVALUATOR_DATA_DIR:-}" ]]; then
  echo "Evaluator data must not be exposed to Agent setup" >&2
  exit 2
fi
if [[ -n "${BPB_H2_DATA_DIR:-}" ]]; then
  "$PYTHON_BIN" "$SHARED/stage.py" --task h2 --source "$BPB_H2_DATA_DIR" \
    --stage-to "${BPB_H2_STAGE_DIR:-$PWD/public_data}"
  exit 0
fi
: "${BPB_H2_DERIVED_ROOT:?Set BPB_H2_DERIVED_ROOT or BPB_H2_DATA_DIR}"
if [[ -n "${BPB_H2_SOURCE_ROOT:-}" && -n "${BPB_H2_CONTENT_CACHE_ROOT:-}" ]]; then
  echo "Choose one source root or content cache" >&2
  exit 2
fi
if [[ -n "${BPB_H2_SOURCE_ROOT:-}" ]]; then
  "$PYTHON_BIN" "$SHARED/export.py" --task h2 --access public \
    --source-root "$BPB_H2_SOURCE_ROOT" --output-root "$BPB_H2_DERIVED_ROOT"
elif [[ -n "${BPB_H2_CONTENT_CACHE_ROOT:-}" ]]; then
  "$PYTHON_BIN" "$SHARED/export.py" --task h2 --access public \
    --content-cache-root "$BPB_H2_CONTENT_CACHE_ROOT" --output-root "$BPB_H2_DERIVED_ROOT"
else
  echo "Set BPB_H2_SOURCE_ROOT or BPB_H2_CONTENT_CACHE_ROOT" >&2
  exit 2
fi
"$PYTHON_BIN" "$SHARED/stage.py" --task h2 --source "$BPB_H2_DERIVED_ROOT/public" \
  --stage-to "${BPB_H2_STAGE_DIR:-$PWD/public_data}"
