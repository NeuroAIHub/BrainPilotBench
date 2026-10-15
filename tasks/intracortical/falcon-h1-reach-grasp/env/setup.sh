#!/usr/bin/env bash
set -euo pipefail

TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${BPB_H1_PYTHON:-python3}"

if [[ "${1:-}" == "--role" && "${2:-}" != "agent" ]]; then
  echo "H1 setup only prepares public Train/Valid data; evaluator Test uses a separate owner workflow" >&2
  exit 2
fi
if [[ -n "${BPB_H1_EVALUATOR_DATA_DIR:-}" ]]; then
  echo "Do not expose BPB_H1_EVALUATOR_DATA_DIR to Agent setup" >&2
  exit 2
fi

if [[ -n "${BPB_H1_DATA_DIR:-}" ]]; then
  "$PYTHON_BIN" "$TASK_DIR/env/stage_public.py" \
    --source "$BPB_H1_DATA_DIR" --stage-to "${BPB_H1_STAGE_DIR:-$PWD/public_data}"
  unset BPB_H1_SOURCE_ROOT BPB_H1_CONTENT_CACHE_ROOT BPB_H1_DERIVED_ROOT BPB_H1_EVALUATOR_DATA_DIR
  exit 0
fi

if [[ -z "${BPB_H1_DERIVED_ROOT:-}" ]]; then
  echo "Set BPB_H1_DATA_DIR to an existing public root, or BPB_H1_DERIVED_ROOT for a new export" >&2
  exit 2
fi
if [[ -n "${BPB_H1_SOURCE_ROOT:-}" && -n "${BPB_H1_CONTENT_CACHE_ROOT:-}" ]]; then
  echo "Choose one exact source tree or BPB content-cache root" >&2
  exit 2
fi
if [[ -n "${BPB_H1_SOURCE_ROOT:-}" ]]; then
  "$PYTHON_BIN" "$TASK_DIR/env/export_h1.py" --access public \
    --source-root "$BPB_H1_SOURCE_ROOT" --output-root "$BPB_H1_DERIVED_ROOT"
elif [[ -n "${BPB_H1_CONTENT_CACHE_ROOT:-}" ]]; then
  "$PYTHON_BIN" "$TASK_DIR/env/export_h1.py" --access public \
    --content-cache-root "$BPB_H1_CONTENT_CACHE_ROOT" --output-root "$BPB_H1_DERIVED_ROOT"
else
  echo "Set BPB_H1_SOURCE_ROOT or BPB_H1_CONTENT_CACHE_ROOT to verified public NWB sources" >&2
  exit 2
fi

"$PYTHON_BIN" "$TASK_DIR/env/stage_public.py" \
  --source "$BPB_H1_DERIVED_ROOT/public" --stage-to "${BPB_H1_STAGE_DIR:-$PWD/public_data}"
unset BPB_H1_SOURCE_ROOT BPB_H1_CONTENT_CACHE_ROOT BPB_H1_DERIVED_ROOT BPB_H1_EVALUATOR_DATA_DIR
