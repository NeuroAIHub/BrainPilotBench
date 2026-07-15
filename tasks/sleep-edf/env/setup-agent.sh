#!/bin/bash
# Stage public sleep-edf data (subjects 0-15 EDF + Hypnogram + manifests
# + loader) into the current agent workspace. Optional loso-supplement
# (subjects 16-19 mirror, for LOSO explorers) is opt-in via
# BPB_SLEEP_EDF_INCLUDE_LOSO=1.
set -euo pipefail

CACHE_ROOT="${BPB_CACHE_ROOT:-${XDG_CACHE_HOME:-$HOME/.cache}/brainpilot-bench}"
SHA_MAIN="4878fe56696cf3614328b07b990116c8459dc232a09612a59c13ab1903824d76"
SHA_LOSO="15305144631a17eb1cf4e74abee1e0361228874d4c2f1c8cad2a2f0560ae3d31"

require_cache() {
  local sha="$1" label="$2" p="${CACHE_ROOT}/$1/data"
  if [ ! -f "$p" ]; then
    echo "public cache missing (${label}): ${p}" >&2
    echo "run: bp-bench fetch sleep-edf --public" >&2
    exit 1
  fi
  echo "$p"
}

MAIN="$(require_cache "$SHA_MAIN" public-main.tar.zst)"

if ! command -v zstd >/dev/null 2>&1; then
  echo "zstd is required: brew install zstd, or apt install zstd" >&2
  exit 1
fi

mkdir -p public_data
STAGE_TMP="$(mktemp -d)"
trap 'rm -rf "$STAGE_TMP"' EXIT
# public-main.tar.zst top-level entries:
#   sleep-cassette/ (32 files for subjects 0-15)
#   manifests/ (subjects.json, default_split.json, loso_folds.json)
#   get_fold_data.py, label_mapping.json, README.md
zstd -dc "$MAIN" | tar -xf - -C "$STAGE_TMP"

rm -rf public_data/sleep-cassette public_data/manifests
cp -a "$STAGE_TMP/sleep-cassette" public_data/sleep-cassette
cp -a "$STAGE_TMP/manifests" public_data/manifests
cp "$STAGE_TMP/get_fold_data.py" public_data/get_fold_data.py
cp "$STAGE_TMP/label_mapping.json" public_data/label_mapping.json
cp "$STAGE_TMP/README.md" public_data/README.md

# Optional LOSO supplement — off by default; only needed for agents that
# want to train over all 20 subjects instead of the default 0-13 train
# split. Under the fixed benchmark split, subjects 16-19 are the private
# test set and must NOT be used for training/validation.
if [ "${BPB_SLEEP_EDF_INCLUDE_LOSO:-0}" = "1" ]; then
  LOSO_PATH="${CACHE_ROOT}/${SHA_LOSO}/data"
  if [ ! -f "$LOSO_PATH" ]; then
    echo "loso-supplement cache missing: $LOSO_PATH" >&2
    echo "  agents that want the LOSO extras should also run: bp-bench fetch sleep-edf --public" >&2
    echo "  ...then set BPB_SLEEP_EDF_INCLUDE_LOSO=1 and rerun this script." >&2
    exit 1
  fi
  STAGE_LOSO="$(mktemp -d)"
  # cleanup piggybacks on the outer trap by nesting
  ( trap 'rm -rf "$STAGE_LOSO"' EXIT; zstd -dc "$LOSO_PATH" | tar -xf - -C "$STAGE_LOSO"
    cp -a "$STAGE_LOSO/sleep-cassette/." public_data/sleep-cassette/
    if [ -f "$STAGE_LOSO/README.md" ]; then
      cp "$STAGE_LOSO/README.md" public_data/LOSO_SUPPLEMENT_README.md
    fi
  )
  echo "  (staged LOSO supplement — subject 16-19 recordings merged into public_data/sleep-cassette/)"
  echo "  NOTE: under the fixed benchmark split, subjects 16-19 are the private test set;"
  echo "        do not use them for training or validation. See LOSO_SUPPLEMENT_README.md."
fi

echo "staged public sleep-edf data in $PWD/public_data"
