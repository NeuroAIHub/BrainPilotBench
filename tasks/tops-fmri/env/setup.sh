#!/bin/bash
# Role dispatcher. The safe default stages public data for the agent only.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
role="agent"
if [ "${1:-}" = "--role" ]; then
  role="${2:-}"
  shift 2
fi

case "$role" in
  agent) exec /bin/bash "$SCRIPT_DIR/setup-agent.sh" "$@" ;;
  evaluator) exec /bin/bash "$SCRIPT_DIR/setup-evaluator.sh" "$@" ;;
  *) echo "unknown setup role: $role (expected agent or evaluator)" >&2; exit 2 ;;
esac
