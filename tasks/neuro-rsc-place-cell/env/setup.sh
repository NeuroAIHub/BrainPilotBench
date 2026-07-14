#!/bin/bash
# env/setup.sh —— 把已 fetch 的 VRBeltReframe.mat 从内容寻址缓存 symlink 到 agent workspace 的 ./data/。
# 契约:在 bp-bench fetch 之后、agent 启动之前跑;cwd = agent workspace 根。
# 内置 adapter 会自动调用；脚本也可用于独立 harness 的手动 staging。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CACHE_ROOT="${XDG_CACHE_HOME:-$HOME/.cache}/brainpilot-bench"
# sha 与 data.lock 中的 sha256 一致(改数据版本请同时改这两处;两侧漂移会明显报错)。
SHA="0a5f35ccf29ce6611908f5233b4325bfcc43e63c57e4d3763a4cf7dcea6f0987"
SRC="${CACHE_ROOT}/${SHA}/data"

if [ ! -f "$SRC" ]; then
  echo "缓存缺失:${SRC}" >&2
  echo "先跑:bp-bench fetch neuro-rsc-place-cell" >&2
  exit 1
fi

mkdir -p data
ln -sfn "$SRC" data/VRBeltReframe.mat

# The schema is public Agent input. Do not stage checks/check.sh,
# checks/reference.json, or the reference implementation.
mkdir -p checks
cp "$SCRIPT_DIR/../checks/output_schema.json" checks/output_schema.json

echo "staged: data/VRBeltReframe.mat → $SRC"
echo "staged: checks/output_schema.json"
