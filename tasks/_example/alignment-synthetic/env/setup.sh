#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
shared="$here/../../../alignment/_shared"
python="${BPB_ALIGNMENT_PYTHON:-python3}"
# Prepare is idempotent only for an intact, existing packet; never silently overwrite.
if [ -d inputs ]; then
  "$python" -B -c 'import sys; sys.path.insert(0, sys.argv[1]); from contract import load_packet; load_packet("inputs")' "$shared"
else
  "$python" -B "$shared/fixtures.py" --output inputs
fi
cp "$here/../contract.json" ./ALIGNMENT_CONTRACT.json
mkdir -p schemas
cp "$here/../schemas/"*.json schemas/
