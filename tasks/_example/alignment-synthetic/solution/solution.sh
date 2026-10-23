#!/usr/bin/env bash
# For the example Oracle/NOP gate only. Every result is computed from generated X/Y.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
shared="$here/../../../alignment/_shared"
python="${BPB_ALIGNMENT_PYTHON:-python3}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
"$python" -B "$shared/fixtures.py" --output "$tmp/inputs"
mkdir -p artifacts/submission
cp "$here/analyze.py" artifacts/submission/
cp "$shared/contract.py" artifacts/submission/alignment_contract.py
"$python" -B artifacts/submission/analyze.py --inputs "$tmp/inputs" --output artifacts
cat > meta.json <<'EOF'
{"taskId":"alignment-synthetic","taskVersion":"0.1","agent":"synthetic-reference-not-agent-benchmark"}
EOF
