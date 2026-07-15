#!/bin/bash
# Stage gated session-E GDF + true_labels into an explicit evaluator-only
# directory. Also stages public.tar.zst (session-T GDF) into the same dir,
# because the scorer must train per subject on the T session and evaluate
# on E — the agent workspace's public copy is not available to the scorer
# at grading time.
set -euo pipefail

CACHE_ROOT="${BPB_CACHE_ROOT:-${XDG_CACHE_HOME:-$HOME/.cache}/brainpilot-bench}"
SHA_PUBLIC="a61fb8ecc83f826324ffb7ae578c546768b4ac975018340b5f2fdad3734b09a5"
SHA_PRIVATE="69dab17fe8d8b56d4d13e576cfa50ad0cb6b64a76de61c4f8534bc172c17e113"

if [ -z "${BPB_BCI2A_PRIVATE_EVAL_DIR:-}" ]; then
  echo "BPB_BCI2A_PRIVATE_EVAL_DIR must point to an evaluator-only directory" >&2
  exit 2
fi

require_cache() {
  local sha="$1" label="$2" p="${CACHE_ROOT}/$1/data"
  if [ ! -f "$p" ]; then
    echo "cache missing (${label}): ${p}" >&2
    echo "run (maintainers only): bp-bench fetch bciciv-2a --private" >&2
    exit 1
  fi
  echo "$p"
}

PUBLIC="$(require_cache "$SHA_PUBLIC" public.tar.zst)"
PRIVATE="$(require_cache "$SHA_PRIVATE" private.tar.zst)"

if ! command -v zstd >/dev/null 2>&1; then
  echo "zstd is required: brew install zstd, or apt install zstd" >&2
  exit 1
fi

WORKSPACE="$(pwd -P)"
mkdir -p "$BPB_BCI2A_PRIVATE_EVAL_DIR"
EVAL_DIR="$(cd "$BPB_BCI2A_PRIVATE_EVAL_DIR" && pwd -P)"
case "$EVAL_DIR/" in
  "$WORKSPACE/"|"$WORKSPACE/"*)
    echo "private evaluator data must be outside the agent workspace: $WORKSPACE" >&2
    exit 2
    ;;
esac

STAGE_TMP="$(mktemp -d)"
trap 'rm -rf "$STAGE_TMP"' EXIT
mkdir -p "$STAGE_TMP/pub" "$STAGE_TMP/priv"
# Untar into distinct subdirs; both tarballs' top-level dirs are named `gdf/`.
zstd -dc "$PUBLIC" | tar -xf - -C "$STAGE_TMP/pub"
zstd -dc "$PRIVATE" | tar -xf - -C "$STAGE_TMP/priv"

mkdir -p "$EVAL_DIR/train_gdf" "$EVAL_DIR/test_gdf" "$EVAL_DIR/true_labels" "$EVAL_DIR/manifests"
# Session-T GDF (public) — scorer's training input (9 files: A0[1-9]T.gdf)
cp -a "$STAGE_TMP/pub/gdf/." "$EVAL_DIR/train_gdf/"
# Session-E GDF (private) — scorer's held-out test input (9 files: A0[1-9]E.gdf)
cp -a "$STAGE_TMP/priv/gdf/." "$EVAL_DIR/test_gdf/"
# True labels (private) — 9 MATLAB .mat files, hidden from the agent
cp -a "$STAGE_TMP/priv/true_labels/." "$EVAL_DIR/true_labels/"
# get_subject_data.py + manifests give the scorer the same train/val split
# indices that the agent saw, so the evaluator's held-out split matches
# exactly what the agent's prompt described.
cp -a "$STAGE_TMP/pub/manifests/." "$EVAL_DIR/manifests/"
cp "$STAGE_TMP/pub/get_subject_data.py" "$EVAL_DIR/get_subject_data.py"

echo "staged bciciv-2a evaluator data in $EVAL_DIR"
echo "  $EVAL_DIR/train_gdf/    (9 × A0xT.gdf, public session T)"
echo "  $EVAL_DIR/test_gdf/     (9 × A0xE.gdf, private session E)"
echo "  $EVAL_DIR/true_labels/  (9 × A0xE.mat, private ground truth)"
echo "  $EVAL_DIR/manifests/    (subjects.json / protocol.json)"
