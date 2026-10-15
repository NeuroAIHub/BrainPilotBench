#!/usr/bin/env bash
set -euo pipefail

TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${BPB_FILM_PUBLIC_ROOT:?Set BPB_FILM_PUBLIC_ROOT to the isolated public-only package}"
# The trusted Oracle/NOP parent also needs the owner root for its later scorer.
# Its reference-generation child receives only the public root. Agent setup
# remains a separate boundary and still rejects owner variables entirely.
unset BPB_FILM_EVALUATOR_DATA_ROOT BPB_FILM_DATA_ROOT BPB_LOCAL_DATA_ROOT BPB_FILM_OWNER_TEST
mkdir -p "$PWD/artifacts"
exec "${BPB_FILM_PYTHON:-python3}" "$TASK_DIR/solution/make_reference.py" \
  --public-data "$BPB_FILM_PUBLIC_ROOT" --submission "$PWD/artifacts/submission"
