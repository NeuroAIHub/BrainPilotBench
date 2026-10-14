#!/usr/bin/env bash
set -euo pipefail
TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$TASK_DIR/../../.." && pwd)"
PYTHON="${BPB_PYTHON:-python3}"
VENV="${BPB_EEG_VENV:-$REPO_ROOT/.cache/eeg/host-venv}"
"$PYTHON" -c 'import sys; assert sys.version_info[:2] in [(3,11),(3,12),(3,13)], "Use Python 3.11, 3.12 or 3.13"'
"$PYTHON" -m venv "$VENV"
if command -v uv >/dev/null 2>&1; then
  uv pip install --system-certs --python "$VENV/bin/python" numpy==2.2.6
else
  "$VENV/bin/python" -m pip install --disable-pip-version-check numpy==2.2.6
fi
echo "Host scorer installed. Set BPB_EEG_PYTHON=$VENV/bin/python"
