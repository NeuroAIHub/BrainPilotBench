#!/usr/bin/env bash
set -euo pipefail

TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${BPB_FILM_PUBLIC_ROOT:=${BPB_PUBLIC_DATA_ROOT:-}}"
BPB_FILM_PUBLIC_ROOT="${BPB_PUBLIC_DATA_ROOT:-$BPB_FILM_PUBLIC_ROOT}"
: "${BPB_FILM_PUBLIC_ROOT:?Set BPB_FILM_PUBLIC_ROOT or BPB_PUBLIC_DATA_ROOT to an isolated public-only package}"
if [[ -n "${BPB_FILM_DATA_ROOT:-}" || -n "${BPB_FILM_EVALUATOR_DATA_ROOT:-}" || -n "${BPB_FILM_OWNER_TEST:-}" ]]; then
  echo "Agent setup cannot receive the owner data root or owner Test state" >&2
  exit 2
fi
exec "${BPB_FILM_PYTHON:-python3}" "$TASK_DIR/env/stage_public.py" \
  --public-root "$BPB_FILM_PUBLIC_ROOT" --destination "${BPB_FILM_STAGE_DIR:-$PWD/public_data}"
