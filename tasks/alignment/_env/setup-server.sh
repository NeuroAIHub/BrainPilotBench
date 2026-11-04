#!/usr/bin/env bash
# Explicit server operation. Nothing is installed unless --install is supplied.
set -euo pipefail
if [[ "${1:-}" != "--install" ]]; then
  echo 'Usage: BPB_ALIGNMENT_VENV=/outside/git/venv BPB_PYTHON=python3.11 bash setup-server.sh --install' >&2
  exit 2
fi
if [[ "$(uname -s)" != Linux ]]; then
  echo 'This bootstrap is for the Linux test server; do not install the real runtime on the development Mac.' >&2
  exit 2
fi
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository="$(cd "$here/../../.." && pwd)"
python="${BPB_PYTHON:-python3.11}"
: "${BPB_ALIGNMENT_VENV:?Set an absolute virtual-environment path outside the repository}"
"$python" - "$repository" "$BPB_ALIGNMENT_VENV" <<'PY'
from pathlib import Path
import sys
if sys.version_info[:2] != (3, 11):
    raise SystemExit('Use Python 3.11: the pinned xarray backend is incompatible with Python 3.12+.')
repository, environment = (Path(value).resolve() for value in sys.argv[1:])
if repository == environment or repository in environment.parents:
    raise SystemExit('Choose a virtual environment outside Git.')
PY
if [[ ! -x "$BPB_ALIGNMENT_VENV/bin/python" ]]; then
  "$python" -m venv "$BPB_ALIGNMENT_VENV"
fi
"$BPB_ALIGNMENT_VENV/bin/python" -m pip install -r "$here/requirements-server.txt"
"$BPB_ALIGNMENT_VENV/bin/python" -m pip check
"$BPB_ALIGNMENT_VENV/bin/python" -m pip freeze --all > "$BPB_ALIGNMENT_VENV/requirements.resolved.txt"
echo "Environment installed. Resolved versions: $BPB_ALIGNMENT_VENV/requirements.resolved.txt"
echo 'No model or brain data has been prepared by this script. Run doctor, then the explicit preparation commands.'
