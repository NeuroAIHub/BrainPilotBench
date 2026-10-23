#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python="${BPB_ALIGNMENT_PROFILE_PYTHON:-python3}"
if [ ! -e PROFILE_CONTEXT.json ]; then
  "$python" -B "$here/../lib/fixtures.py" --output PROFILE_CONTEXT.json --public-only
else
  "$python" -B - "$here/../lib" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from core import PROFILE, read_json
context = read_json('PROFILE_CONTEXT.json')
if not isinstance(context, dict) or context.get('protocol_id') != PROFILE or context.get('synthetic_only') is not True:
    raise SystemExit('Existing profile context is incompatible; use a new workspace for this task version.')
PY
fi
cp "$here/../protocol.json" PROFILE_PROTOCOL.json
cp "$here/../CONTRACT.md" PROFILE_CONTRACT.md
mkdir -p schemas
cp "$here/../schemas/answers.schema.json" schemas/
# The operator supplies a separately launched MCP service. No target data,
# authoritative ledger, reference solution, or network downloader is staged.
