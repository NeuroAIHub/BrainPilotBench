#!/bin/bash
# Install the task's isolated Python 3.11 environment with verified TLS.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../../../.." && pwd)"
cache_root="${BPB_BRAIN_AGE_CACHE_ROOT:-$repo_root/.cache/brain-age}"
venv="$cache_root/venv"
mkdir -p "$cache_root"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to create the isolated brain-age environment" >&2
  exit 1
fi

uv python install 3.11 --install-dir "$cache_root/python" --cache-dir "$cache_root/uv-cache" --system-certs
python_path="$(find "$cache_root/python" -type f -name python3.11 -print -quit)"
if [ -z "$python_path" ]; then
  echo "uv did not install Python 3.11 under $cache_root/python" >&2
  exit 1
fi
uv venv "$venv" --python "$python_path" --no-project --cache-dir "$cache_root/uv-cache" --system-certs
uv pip install --python "$venv/bin/python" -r "$script_dir/requirements.txt" --cache-dir "$cache_root/uv-cache" --system-certs
"$venv/bin/python" - <<'PY'
import sys
import numpy, scipy, nibabel, sklearn, threadpoolctl
assert sys.version_info[:2] == (3, 11), sys.version
print(f"brain-age Python ready: {sys.version.split()[0]}, numpy={numpy.__version__}, scipy={scipy.__version__}, nibabel={nibabel.__version__}, sklearn={sklearn.__version__}")
PY
