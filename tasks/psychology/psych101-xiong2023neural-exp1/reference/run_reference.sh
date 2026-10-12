#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TASK_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SHARED="$(cd "$SCRIPT_DIR/../../_shared" && pwd)"
if [ "$#" -ne 1 ]; then echo "usage: run_reference.sh <new-output-directory>" >&2; exit 2; fi
exec python3 "$SHARED/byte_reference.py" --contract "$TASK_DIR/contract.json" --public-dir "${BPB_PSYCH101_PUBLIC_DIR:-$PWD/public_data}" --out "$1"
