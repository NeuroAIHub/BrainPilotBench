#!/bin/bash
# Stage gated subject-16-19 EDF + Hypnogram into an evaluator-only dir.
# Also stages public-main.tar.zst (subjects 0-15 EDF + Hypnogram) into
# the same dir, because the scorer must train on subjects 0-13 and
# validate on 14-15 — the agent workspace's public copy is not available
# to the scorer at grading time.
set -euo pipefail

CACHE_ROOT="${BPB_CACHE_ROOT:-${XDG_CACHE_HOME:-$HOME/.cache}/brainpilot-bench}"
SHA_MAIN="4878fe56696cf3614328b07b990116c8459dc232a09612a59c13ab1903824d76"
SHA_PRIVATE="bd5550c3643b2da0c89b571fd7b03fee19dcb67744400a0cc49ea5cef74d1d1a"

if [ -z "${BPB_SLEEP_EDF_PRIVATE_EVAL_DIR:-}" ]; then
  echo "BPB_SLEEP_EDF_PRIVATE_EVAL_DIR must point to an evaluator-only directory" >&2
  exit 2
fi

require_cache() {
  local sha="$1" label="$2" p="${CACHE_ROOT}/$1/data"
  if [ ! -f "$p" ]; then
    echo "cache missing (${label}): ${p}" >&2
    echo "run (maintainers only): bp-bench fetch sleep-edf --private" >&2
    exit 1
  fi
  echo "$p"
}

MAIN="$(require_cache "$SHA_MAIN" public-main.tar.zst)"
PRIVATE="$(require_cache "$SHA_PRIVATE" private.tar.zst)"

if ! command -v zstd >/dev/null 2>&1; then
  echo "zstd is required: brew install zstd, or apt install zstd" >&2
  exit 1
fi

WORKSPACE="$(pwd -P)"
mkdir -p "$BPB_SLEEP_EDF_PRIVATE_EVAL_DIR"
EVAL_DIR="$(cd "$BPB_SLEEP_EDF_PRIVATE_EVAL_DIR" && pwd -P)"
case "$EVAL_DIR/" in
  "$WORKSPACE/"|"$WORKSPACE/"*)
    echo "private evaluator data must be outside the agent workspace: $WORKSPACE" >&2
    exit 2
    ;;
esac

STAGE_TMP="$(mktemp -d)"
trap 'rm -rf "$STAGE_TMP"' EXIT
mkdir -p "$STAGE_TMP/pub" "$STAGE_TMP/priv"
# Untar into distinct subdirs; both tarballs' top-level dirs contain a `sleep-cassette/`.
zstd -dc "$MAIN"    | tar -xf - -C "$STAGE_TMP/pub"
zstd -dc "$PRIVATE" | tar -xf - -C "$STAGE_TMP/priv"

mkdir -p "$EVAL_DIR/train_edf" "$EVAL_DIR/test_edf" "$EVAL_DIR/manifests"
# Subjects 0-15 (public) — scorer's training + val input (32 files)
cp -a "$STAGE_TMP/pub/sleep-cassette/." "$EVAL_DIR/train_edf/"
# Subjects 16-19 (private) — scorer's blind-test input (16 files)
cp -a "$STAGE_TMP/priv/sleep-cassette/." "$EVAL_DIR/test_edf/"
# Manifests + loader — reused so the scorer knows subject → filename mapping
# and default_split subjects (train 0-13, val 14-15, test 16-19).
cp -a "$STAGE_TMP/pub/manifests/." "$EVAL_DIR/manifests/"
cp "$STAGE_TMP/pub/get_fold_data.py" "$EVAL_DIR/get_fold_data.py"

echo "staged sleep-edf evaluator data in $EVAL_DIR"
echo "  $EVAL_DIR/train_edf/    (62 files for subjects 0-15, PSG + Hypnogram)"
echo "  $EVAL_DIR/test_edf/     (16 files for subjects 16-19, PSG + Hypnogram — private)"
echo "  $EVAL_DIR/manifests/    (subjects.json / default_split.json / loso_folds.json)"
