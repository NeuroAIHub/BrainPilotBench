#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${BPB_ALIGNMENT_PROFILE_PYTHON:-python3}" -B "$here/../lib/grader.py" "$PWD"
