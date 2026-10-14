#!/bin/bash
# env/setup-agent.sh —— 铺 **public** 数据到 Agent 工作区。
#
# 数据由 data.lock 钉死（3 项 public，全部 https + commit sha 锁定），默认直接从
# 框架的内容寻址缓存取——即规范流程 `bp-bench run <task> --fetch` 或
# `bp-bench fetch <task> --public` 之后即可工作，无需手工准备目录。
#
# 本脚本由 prepareWorkspace() 以 `setup.sh --role agent`、cwd=Agent 工作区调用，
# 因此所有产物都落在工作区内。**绝不铺 private 数据**（否则
# workflow.ts:assertAgentDataBoundary 会在 Agent 启动前直接抛错）。
set -euo pipefail

# 数据来源（按优先级）：
#   1) 环境变量给出的本地目录（开发时手工准备的原料）
#   2) 框架的内容寻址缓存 <XDG_CACHE_HOME>/brainpilot-bench/<sha256>/data
#      —— `bp-bench fetch celegans-structure-function-divergence --public` 拉取并校验
CACHE_ROOT="${BPB_CACHE_ROOT:-${XDG_CACHE_HOME:-$HOME/.cache}/brainpilot-bench}"

cache_file() {   # <sha256> <label> → 打印缓存中的文件路径
  local p="${CACHE_ROOT}/$1/data"
  if [ ! -f "$p" ]; then
    echo "[setup-agent] 数据不在框架缓存中（$2）: $p" >&2
    echo "  请先运行: bp-bench fetch celegans-structure-function-divergence --public" >&2
    exit 1
  fi
  printf '%s' "$p"
}

SHA_CONN="f02c68c9a2d34fe7b5aa8c7d74d8aca9ea9676d647e794ba99abbbff1b6350e5"
SHA_W7="613bfa8fb52f0ec85d65c5a878f6a40620e6c960337a4d1d1ac2ffa2af2d6e57"
SHA_META="f3273b529c7542cf6b1d61b438d0e87526e32166b74d464fcaefe4700d87a558"

PUBLIC_DIR="${BPB_CELEGANS_DIVERGENCE_PUBLIC_DIR:-}"
if [ -z "$PUBLIC_DIR" ]; then
  # 从框架缓存取三份 public 文件到一个临时目录，后续走同一条组装路径。
  STAGE="$(mktemp -d "${TMPDIR:-/tmp}/bpb-celegans-public.XXXXXX")"
  trap 'rm -rf "$STAGE"' EXIT
  cp "$(cache_file "$SHA_CONN" CElegansFunctionalConnectivity.xlsx)" \
     "$STAGE/CElegansFunctionalConnectivity.xlsx"
  cp "$(cache_file "$SHA_W7" witvliet_2020_7.csv)" "$STAGE/witvliet_2020_7.csv"
  cp "$(cache_file "$SHA_META" neuron_master_sheet.csv)" "$STAGE/neuron_master_sheet.csv"
  PUBLIC_DIR="$STAGE"
fi

mkdir -p public
PY="${BPB_PYTHON:-python3}"

# Git Bash(MSYS) 下把 /f/... 转成 F:/... 再交给原生 python.exe；
# Linux/macOS 上无 cygpath，本函数是空操作。
towl() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi; }

"$PY" - "$(towl "$PUBLIC_DIR")" <<'PY'
import os
import sys

import numpy as np
import pandas as pd

src = sys.argv[1]


def need(*names):
    """按 data.lock 声明的文件名解析；同时兼容历史本地名。"""
    for n in names:
        p = os.path.join(src, n)
        if os.path.isfile(p):
            return p
    raise SystemExit(f"[setup-agent] 缺数据文件（候选名 {names}）于 {src}")


# ---- 信号图谱 + 显著性 ----
xl = pd.ExcelFile(need("CElegansFunctionalConnectivity.xlsx", "func_conn.xlsx"))
raw = xl.parse("Figure2a, df_over_f", header=None)
ids = [str(x).strip() for x in raw.iloc[0, 1:]]
M = raw.iloc[1:, 1:].to_numpy(dtype=float)
Aa = xl.parse("Figure2a, alpha=(1 - q_val)", header=None).iloc[1:, 1:].to_numpy(dtype=float)
assert M.shape == (len(ids), len(ids)) and Aa.shape == M.shape
np.savez_compressed("public/signaling.npz", matrix=M, alpha=Aa,
                    neuron_ids=np.array(ids, dtype=np.str_))

# ---- 公开连接组（witvliet_2020_7；评测用其余版本，agent 不可见）----
df = pd.read_csv(need("witvliet_2020_7.csv"), sep="\t")
df.columns = [c.strip().lower() for c in df.columns]
nodes = sorted(set(df["pre"]) | set(df["post"]))
pos = {x: i for i, x in enumerate(nodes)}
A = np.zeros((len(nodes), len(nodes)), dtype=np.uint8)
for pre, post in zip(df["pre"], df["post"]):
    if pre != post:
        i, j = pos[pre], pos[post]
        A[i, j] = 1
        A[j, i] = 1
np.savez_compressed("public/connectome_witvliet_2020_7.npz", adjacency=A,
                    neuron_ids=np.array(nodes, dtype=np.str_))

# ---- 元数据 ----
ms = pd.read_csv(need("neuron_master_sheet.csv"))
keep = [c for c in ("label", "class", "type", "neurotransmitter", "x", "y", "z")
        if c in ms.columns]
ms[keep].to_csv("public/neuron_metadata.csv", index=False)

n = A.sum() / (len(nodes) * (len(nodes) - 1))
# 断言：public 连接组是纯体神经系统导出（不含咽部神经元）——题面已声明此事，
# 若上游换了版本，这里会先失败，避免题面与数据不符。
ph = {"I1L", "I1R", "I2L", "I2R", "I3", "I4", "I5", "I6", "M1", "M2L", "M2R", "M3L",
      "M3R", "M4", "M5", "MC1DL", "MC1DR", "MC1VL", "MC1VR", "MCL", "MCR", "MI",
      "NSML", "NSMR"}
assert not (ph & set(nodes)), "public 连接组含咽部神经元，与题面声明不符"
print(f"[setup-agent] public: signaling {M.shape}, connectome N={len(nodes)} "
      f"密度={n:.4f}（无咽部神经元，符合预期）")
PY

echo "[setup-agent] public data written under ./public"
