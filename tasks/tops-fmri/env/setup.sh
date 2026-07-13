#!/bin/bash
# env/setup.sh —— 从内容寻址缓存把公开数据 stage 到 agent workspace,并把私有 features/labels
# stage 到 workspace **外**的一个 scorer-only 目录($BPB_TOPS_PRIVATE_EVAL_DIR)。
#
# 契约:
#   * bp-bench fetch 之后、agent 启动之前跑。
#   * cwd = agent workspace 根。agent 只应看见 public_data/。
#   * 私有 features/labels 必须落在 workspace 之外(此脚本用 workspace 的兄弟目录)。
#   * runner 尚未自动执行 env/setup.sh(SUT adapter 阶段落地),现阶段由 wrapper 手动跑。
set -euo pipefail

CACHE_ROOT="${XDG_CACHE_HOME:-$HOME/.cache}/brainpilot-bench"

# 与 data.lock 中的 sha256 对齐(改数据版本同时改两处;不同步会立即报错)。
SHA_STUDY3="17ca43dbc6ec53f9d9a1ae7b5ad234160d1dfee96dc5d83c714dd4cf87ae7366"
SHA_PUBLIC="051316b32ffe0b39d32ef1a577d82f6c18e5a90425d9082367566cd7b83204d2"
SHA_PRIV_F="e709d9c3fa5ab067dd58d0ad205185423dad7e531bba8c7466e1d24bef924c56"
SHA_PRIV_L="95bc997c345fbe7429a5f5f4d850f782faaf9616c3a9074b8e34efa0b5aabb58"

require_cache() {
  local sha="$1" label="$2"
  local p="${CACHE_ROOT}/${sha}/data"
  if [ ! -f "$p" ]; then
    echo "缓存缺失(${label}): ${p}" >&2
    echo "先跑:bp-bench fetch tops-fmri" >&2
    exit 1
  fi
  echo "$p"
}

STUDY3="$(require_cache "$SHA_STUDY3" study3_train.mat)"
PUBLIC="$(require_cache "$SHA_PUBLIC" public_support.tar.zst)"
PRIV_F="$(require_cache "$SHA_PRIV_F" private_features.tar.zst)"
PRIV_L="$(require_cache "$SHA_PRIV_L" private_labels.tar.zst)"

# ===== 1. 公开数据 → agent workspace(./public_data/) =====
mkdir -p public_data/whole_participants/FC_and_pain
ln -sfn "$STUDY3" public_data/whole_participants/FC_and_pain/study3_train.mat

# tar.zst 需要 zstd; ubuntu/alpine 通常预装。缺失时明确报错。
if ! command -v zstd >/dev/null 2>&1; then
  echo "zstd 未安装:sudo apt install -y zstd  (或 brew install zstd)" >&2
  exit 1
fi
STAGE_TMP="$(mktemp -d)"
trap 'rm -rf "$STAGE_TMP"' EXIT
tar -I zstd -xf "$PUBLIC" -C "$STAGE_TMP"
# tar 内顶层是 public_support/{atlas,example_participant}
cp -a "$STAGE_TMP/public_support/atlas"                public_data/atlas
cp -a "$STAGE_TMP/public_support/example_participant"  public_data/example_participant
echo "staged public_data/{study3_train.mat, atlas/, example_participant/}"

# ===== 2. 私有数据 → workspace 外的 scorer-only 目录 =====
# BPB_TOPS_PRIVATE_EVAL_DIR 默认落在 workspace 的**父目录**下的兄弟位置,保证 agent
# `ls /path/to/workspace/..` 才可能看到 —— 现在的 sandbox 是本地子进程,还没有强
# workspace 隔离;Docker sandbox 阶段落地时,这个目录会挂载到 scorer 侧、不进 agent。
if [ -z "${BPB_TOPS_PRIVATE_EVAL_DIR:-}" ]; then
  export BPB_TOPS_PRIVATE_EVAL_DIR="$(cd .. && pwd)/tops-fmri-private-eval"
fi
mkdir -p "$BPB_TOPS_PRIVATE_EVAL_DIR/features" "$BPB_TOPS_PRIVATE_EVAL_DIR/labels"

STAGE_TMP2="$(mktemp -d)"
tar -I zstd -xf "$PRIV_F" -C "$STAGE_TMP2"
tar -I zstd -xf "$PRIV_L" -C "$STAGE_TMP2"
cp -a "$STAGE_TMP2/private_features/features/." "$BPB_TOPS_PRIVATE_EVAL_DIR/features/"
cp -a "$STAGE_TMP2/private_labels/labels/."     "$BPB_TOPS_PRIVATE_EVAL_DIR/labels/"
rm -rf "$STAGE_TMP2"

echo "staged private eval dir: $BPB_TOPS_PRIVATE_EVAL_DIR (scorer only)"
echo "export BPB_TOPS_PRIVATE_EVAL_DIR='$BPB_TOPS_PRIVATE_EVAL_DIR' > .env  ← scorer 需要"

# 把 env 变量记到 .env,方便 wrapper / check.sh 读(agent workspace 里的 .env 不会
# 被 sandbox 自动 source,scorer/check.sh 需要显式读)。
{
  echo "BPB_TOPS_PRIVATE_EVAL_DIR=$BPB_TOPS_PRIVATE_EVAL_DIR"
} > ../.tops-fmri.env 2>/dev/null || true
