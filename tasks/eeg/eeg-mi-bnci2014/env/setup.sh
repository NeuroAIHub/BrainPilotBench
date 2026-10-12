#!/usr/bin/env bash
set -euo pipefail
TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ "${1:-}" = "--role" ]; then
  case "${2:-}" in agent|evaluator) ;; *) echo "invalid role" >&2; exit 2;; esac
fi
exec python3 "$TASK_DIR/env/prepare.py" --task "$TASK_DIR" --output "$PWD/public_data"
