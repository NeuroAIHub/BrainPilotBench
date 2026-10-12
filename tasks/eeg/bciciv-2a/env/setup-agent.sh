#!/bin/bash
# Stage public bciciv-2a data (subject T-session GDF + manifests + loader)
# into the current agent workspace.
set -euo pipefail

CACHE_ROOT="${BPB_CACHE_ROOT:-${XDG_CACHE_HOME:-$HOME/.cache}/brainpilot-bench}"
SHA_PUBLIC="a61fb8ecc83f826324ffb7ae578c546768b4ac975018340b5f2fdad3734b09a5"

require_cache() {
  local sha="$1" label="$2" p="${CACHE_ROOT}/$1/data"
  if [ ! -f "$p" ]; then
    echo "public cache missing (${label}): ${p}" >&2
    echo "run: bp-bench fetch bciciv-2a --public" >&2
    exit 1
  fi
  echo "$p"
}

PUBLIC="$(require_cache "$SHA_PUBLIC" public.tar.zst)"

if ! command -v zstd >/dev/null 2>&1; then
  echo "zstd is required: brew install zstd, or apt install zstd" >&2
  exit 1
fi

# Untar into ./public_data/. The tarball's top-level entries are
# gdf/, manifests/, get_subject_data.py, label_mapping.json, README.md
mkdir -p public_data
STAGE_TMP="$(mktemp -d)"
trap 'rm -rf "$STAGE_TMP"' EXIT
zstd -dc "$PUBLIC" | tar -xf - -C "$STAGE_TMP"

# The submitted MIAgentModel loader will do `sys.path.insert(0, ".../public_data")`
# then `from get_subject_data import get_subject_data`, so the loader has to sit
# at the root of public_data/.
rm -rf public_data/gdf public_data/manifests
cp -a "$STAGE_TMP/gdf" public_data/gdf
cp -a "$STAGE_TMP/manifests" public_data/manifests
cp "$STAGE_TMP/get_subject_data.py" public_data/get_subject_data.py
cp "$STAGE_TMP/label_mapping.json" public_data/label_mapping.json
cp "$STAGE_TMP/README.md" public_data/README.md

echo "staged public bciciv-2a data in $PWD/public_data"
