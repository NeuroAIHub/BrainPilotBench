#!/bin/bash
# Stage public Study3/support data into the current agent workspace.
set -euo pipefail

CACHE_ROOT="${BPB_CACHE_ROOT:-${XDG_CACHE_HOME:-$HOME/.cache}/brainpilot-bench}"
SHA_STUDY3="17ca43dbc6ec53f9d9a1ae7b5ad234160d1dfee96dc5d83c714dd4cf87ae7366"
SHA_PUBLIC="051316b32ffe0b39d32ef1a577d82f6c18e5a90425d9082367566cd7b83204d2"

require_cache() {
  local sha="$1" label="$2" p="${CACHE_ROOT}/$1/data"
  if [ ! -f "$p" ]; then
    echo "public cache missing (${label}): ${p}" >&2
    echo "run: bp-bench fetch tops-fmri --public" >&2
    exit 1
  fi
  echo "$p"
}

STUDY3="$(require_cache "$SHA_STUDY3" study3_train.mat)"
PUBLIC="$(require_cache "$SHA_PUBLIC" public_support.tar.zst)"

if ! command -v zstd >/dev/null 2>&1; then
  echo "zstd is required: brew install zstd, or apt install zstd" >&2
  exit 1
fi

mkdir -p public_data/whole_participants/FC_and_pain
ln -sfn "$STUDY3" public_data/whole_participants/FC_and_pain/study3_train.mat

STAGE_TMP="$(mktemp -d)"
trap 'rm -rf "$STAGE_TMP"' EXIT
tar -I zstd -xf "$PUBLIC" -C "$STAGE_TMP"
rm -rf public_data/atlas public_data/example_participant
cp -a "$STAGE_TMP/public_support/atlas" public_data/atlas
cp -a "$STAGE_TMP/public_support/example_participant" public_data/example_participant

echo "staged public tops-fmri data in $PWD/public_data"
