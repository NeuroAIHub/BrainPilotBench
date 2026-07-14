#!/bin/bash
# Stage gated features/labels into an explicit evaluator-only directory.
set -euo pipefail

CACHE_ROOT="${BPB_CACHE_ROOT:-${XDG_CACHE_HOME:-$HOME/.cache}/brainpilot-bench}"
SHA_PRIV_F="e709d9c3fa5ab067dd58d0ad205185423dad7e531bba8c7466e1d24bef924c56"
SHA_PRIV_L="95bc997c345fbe7429a5f5f4d850f782faaf9616c3a9074b8e34efa0b5aabb58"

if [ -z "${BPB_TOPS_PRIVATE_EVAL_DIR:-}" ]; then
  echo "BPB_TOPS_PRIVATE_EVAL_DIR must point to an evaluator-only directory" >&2
  exit 2
fi

require_cache() {
  local sha="$1" label="$2" p="${CACHE_ROOT}/$1/data"
  if [ ! -f "$p" ]; then
    echo "private cache missing (${label}): ${p}" >&2
    echo "run (maintainers only): bp-bench fetch tops-fmri --private" >&2
    exit 1
  fi
  echo "$p"
}

PRIV_F="$(require_cache "$SHA_PRIV_F" private_features.tar.zst)"
PRIV_L="$(require_cache "$SHA_PRIV_L" private_labels.tar.zst)"

if ! command -v zstd >/dev/null 2>&1; then
  echo "zstd is required: brew install zstd, or apt install zstd" >&2
  exit 1
fi

WORKSPACE="$(pwd -P)"
mkdir -p "$BPB_TOPS_PRIVATE_EVAL_DIR"
EVAL_DIR="$(cd "$BPB_TOPS_PRIVATE_EVAL_DIR" && pwd -P)"
case "$EVAL_DIR/" in
  "$WORKSPACE/"|"$WORKSPACE/"*)
    echo "private evaluator data must be outside the agent workspace: $WORKSPACE" >&2
    exit 2
    ;;
esac

STAGE_TMP="$(mktemp -d)"
trap 'rm -rf "$STAGE_TMP"' EXIT
tar -I zstd -xf "$PRIV_F" -C "$STAGE_TMP"
tar -I zstd -xf "$PRIV_L" -C "$STAGE_TMP"
mkdir -p "$EVAL_DIR/features" "$EVAL_DIR/labels"
cp -a "$STAGE_TMP/private_features/features/." "$EVAL_DIR/features/"
cp -a "$STAGE_TMP/private_labels/labels/." "$EVAL_DIR/labels/"

echo "staged private tops-fmri evaluator data in $EVAL_DIR"
