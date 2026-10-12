#!/usr/bin/env bash
# Install only the trusted host scorer's NumPy dependency into a task cache.
# Submitted models run in the separate pinned Docker inference image.
set -euo pipefail

SHARED_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SHARED_DIR/../../.." && pwd)"
PYTHON="${BPB_PYTHON:-python3}"
VENV="${BPB_EEG_VENV:-$REPO_ROOT/.cache/eeg/host-venv}"

"$PYTHON" -c 'import sys; assert (3,11) <= sys.version_info[:2] <= (3,13), "Use Python 3.11–3.13"'
if [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c 'import numpy; assert numpy.__version__ == "2.2.6"' >/dev/null 2>&1; then
  echo "Reusing pinned host scorer: $VENV/bin/python (numpy 2.2.6)"
else
  "$PYTHON" -m venv "$VENV"
  if command -v uv >/dev/null 2>&1; then
    uv pip install --system-certs --python "$VENV/bin/python" numpy==2.2.6
  else
    "$VENV/bin/python" -m pip install --disable-pip-version-check numpy==2.2.6
  fi
  "$VENV/bin/python" -c 'import numpy; assert numpy.__version__ == "2.2.6"'
  echo "Installed pinned host scorer: $VENV/bin/python (numpy 2.2.6)"
fi
echo "Set BPB_EEG_PYTHON=$VENV/bin/python before public validation."
