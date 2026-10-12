#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TASK_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SHARED="$(cd "$SCRIPT_DIR/../../_shared" && pwd)"
if [ "${1:-}" = "--role" ]; then case "${2:-}" in agent|evaluator) ;; *) echo "invalid role" >&2; exit 2;; esac; fi
if [ -n "${BPB_PSYCH101_PUBLIC_TASK_DIR:-}" ]; then
  exec python3 "$SHARED/prepare_public.py" --contract "$TASK_DIR/contract.json" --published-dir "$BPB_PSYCH101_PUBLIC_TASK_DIR" --output "$PWD/public_data"
fi
CACHE_ROOT="${BPB_CACHE_ROOT:-${XDG_CACHE_HOME:-$HOME/.cache}/brainpilot-bench}"
SOURCE="$CACHE_ROOT/7a370a94084acd6f73f20d6559214683cfadcab8a1f69e369df285ba75ccef01/data"
if [ ! -f "$SOURCE" ]; then echo "Public source cache missing; run bp-bench fetch psych101-feng2021dynamics-exp1 --public" >&2; exit 1; fi
exec python3 "$SHARED/prepare_public.py" --contract "$TASK_DIR/contract.json" --source "$SOURCE" --output "$PWD/public_data"
