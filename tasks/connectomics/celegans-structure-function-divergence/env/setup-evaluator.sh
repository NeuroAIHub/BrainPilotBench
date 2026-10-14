#!/bin/bash
# env/setup-evaluator.sh —— 铺 **私有**评测数据（绝不进 agent 工作区）。
#
# 产出（与 checks/evaluate_external.py 的 resolve_private_dir 约定一致）：
#   <PRIV>/signaling.npz            信号图谱 + alpha（与公开侧同一份）
#   <PRIV>/versions/<name>.npz      每个版本：adjacency + neuron_ids
#
# 数据由 data.lock 钉死（6 项，全部 https + commit sha 锁定），默认直接从框架的
# 内容寻址缓存取——即 `bp-bench fetch celegans-structure-function-divergence --all`
# （或分别 --public / --private）之后即可工作。
#
# BPB_PRIVATE_EVAL_DIR is required and must be outside the task and Agent
# workspace. No legacy variable or task-local fallback is accepted.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TASK_DIR="$(cd "$HERE/.." && pwd)"

# 数据来源（按优先级）：
#   1) 环境变量给出的本地目录（开发时手工准备的原料）
#   2) 框架的内容寻址缓存 <XDG_CACHE_HOME>/brainpilot-bench/<sha256>/data
#      —— `bp-bench fetch celegans-structure-function-divergence --public` 拉取并校验
CACHE_ROOT="${BPB_CACHE_ROOT:-${XDG_CACHE_HOME:-$HOME/.cache}/brainpilot-bench}"

cache_file() {   # <sha256> <label> → 打印缓存中的文件路径
  local p="${CACHE_ROOT}/$1/data"
  if [ ! -f "$p" ]; then
    echo "[setup-evaluator] 数据不在框架缓存中（$2）: $p" >&2
    echo "  请先运行: bp-bench fetch celegans-structure-function-divergence --all" >&2
    exit 1
  fi
  printf '%s' "$p"
}

SHA_CONN="f02c68c9a2d34fe7b5aa8c7d74d8aca9ea9676d647e794ba99abbbff1b6350e5"
SHA_W7="613bfa8fb52f0ec85d65c5a878f6a40620e6c960337a4d1d1ac2ffa2af2d6e57"
SHA_META="f3273b529c7542cf6b1d61b438d0e87526e32166b74d464fcaefe4700d87a558"
SHA_W8="d6627c50f4295291e68c071e001e1e302b03d2d472a7f251f90cb36839e9be1a"
SHA_WHITE="768d2b16557d768b51f81548f630adb45d76c1f99586e8fd4c90279293cc9dae"
SHA_COOK="734202acc42c30a5cce882e695bb2efa333ade5b76345d7e35908342ee640b2c"

OUT="${BPB_PRIVATE_EVAL_DIR:-}"
if [ -z "$OUT" ]; then
  echo "[setup-evaluator] BPB_PRIVATE_EVAL_DIR is required" >&2
  exit 1
fi
case "$OUT" in
  /*) ;;
  *) echo "[setup-evaluator] BPB_PRIVATE_EVAL_DIR must be absolute" >&2; exit 1 ;;
esac
case "$OUT" in
  "$TASK_DIR"|"$TASK_DIR"/*)
    echo "[setup-evaluator] private output must be outside the task directory" >&2
    exit 1 ;;
esac

RAW_DIR="${BPB_CELEGANS_DIVERGENCE_RAW_DIR:-}"
if [ -z "$RAW_DIR" ]; then
  STAGE="$(mktemp -d "${TMPDIR:-/tmp}/bpb-celegans-raw.XXXXXX")"
  trap 'rm -rf "$STAGE"' EXIT
  cp "$(cache_file "$SHA_CONN" CElegansFunctionalConnectivity.xlsx)" \
     "$STAGE/CElegansFunctionalConnectivity.xlsx"
  cp "$(cache_file "$SHA_W7" witvliet_2020_7.csv)" "$STAGE/witvliet_2020_7.csv"
  cp "$(cache_file "$SHA_META" neuron_master_sheet.csv)" "$STAGE/neuron_master_sheet.csv"
  cp "$(cache_file "$SHA_W8" witvliet_2020_8.csv)" "$STAGE/witvliet_2020_8.csv"
  cp "$(cache_file "$SHA_WHITE" aconnectome_white_1986_whole.csv)" \
     "$STAGE/aconnectome_white_1986_whole.csv"
  cp "$(cache_file "$SHA_COOK" cook2019_matlab_ready.zip)" \
     "$STAGE/cook2019_matlab_ready.zip"
  RAW_DIR="$STAGE"
fi

mkdir -p "$OUT/versions"
PY="${BPB_PYTHON:-python3}"

# Git Bash(MSYS) 下把 /f/... 转成 F:/... 再交给原生 python.exe；
# Linux/macOS 上无 cygpath，本函数是空操作。
towl() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi; }

"$PY" - "$(towl "$RAW_DIR")" "$(towl "$OUT")" "$(towl "$TASK_DIR")" <<'PY'
import os
import sys

import numpy as np
import pandas as pd
import scipy.io as sio

raw, out, task_dir = sys.argv[1], sys.argv[2], sys.argv[3]
# 注意：本脚本体在 heredoc 里跑，__file__ 指向 <stdin>，故任务目录由调用方显式传入。
CANON = os.path.join(task_dir, "checks", "neuron_labels_canonical_300.txt")


def need(*names):
    """按 data.lock 声明的文件名解析；同时兼容历史本地名。"""
    for n in names:
        p = os.path.join(raw, n)
        if os.path.isfile(p):
            return p
    raise SystemExit(f"[setup-evaluator] 缺数据文件（候选名 {names}）于 {raw}")


def load_canon():
    with open(CANON, encoding="utf-8") as f:
        return {l.strip() for l in f if l.strip() and not l.startswith("#")}


canon = load_canon()

# ---- 信号图谱（与公开侧同源）----
xl = pd.ExcelFile(need("CElegansFunctionalConnectivity.xlsx", "func_conn.xlsx"))
raw_sig = xl.parse("Figure2a, df_over_f", header=None)
ids = [str(x).strip() for x in raw_sig.iloc[0, 1:]]
M = raw_sig.iloc[1:, 1:].to_numpy(dtype=float)
Aa = xl.parse("Figure2a, alpha=(1 - q_val)", header=None).iloc[1:, 1:].to_numpy(dtype=float)
np.savez_compressed(os.path.join(out, "signaling.npz"), matrix=M, alpha=Aa,
                    neuron_ids=np.array(ids, dtype=np.str_))


def from_edges(path, restrict=None):
    df = pd.read_csv(path, sep="\t")
    df.columns = [c.strip().lower() for c in df.columns]
    if restrict is not None:
        df = df[df["pre"].isin(restrict) & df["post"].isin(restrict)]
    nodes = sorted(set(df["pre"]) | set(df["post"]))
    pos = {x: i for i, x in enumerate(nodes)}
    A = np.zeros((len(nodes), len(nodes)), dtype=np.uint8)
    for pre, post in zip(df["pre"], df["post"]):
        if pre != post and pre in pos and post in pos:
            i, j = pos[pre], pos[post]
            A[i, j] = 1
            A[j, i] = 1
    return nodes, A


def save(name, nodes, adj):
    # 不变量（题面 prompt/turns.yaml 对 adjacency 的声明）：
    #   "undirected, chemical and electrical synapses unioned, max(A, A^T) symmetrised"
    # 这里把声明钉死在生成端——否则真值端 _to_graph 只读上三角，会静默丢掉反向边，
    # 与任何按题面实现的提交得到**不同的边集**（2026-09-18 实测 cook_2019 即如此）。
    adj = np.asarray(adj, dtype=np.uint8)
    assert np.array_equal(adj, adj.T), (
        f"{name}: adjacency 必须对称（题面声明 max(A, A^T)），实测非对称对 "
        f"{int(np.sum(adj[np.triu_indices(len(nodes), 1)] != adj.T[np.triu_indices(len(nodes), 1)]))} 个")
    assert not np.any(np.diag(adj)), f"{name}: adjacency 对角必须为 0（自突触不算连接组边）"
    np.savez_compressed(os.path.join(out, "versions", f"{name}.npz"),
                        adjacency=adj,
                        neuron_ids=np.array(nodes, dtype=np.str_))
    n = len(nodes)
    dens = adj.sum() / (n * (n - 1)) if n > 1 else 0.0
    print(f"[setup-evaluator]   {name}: N={n} 边={int(adj.sum() // 2)} 密度={dens:.4f}")


save("witvliet_2020_8", *from_edges(need("witvliet_2020_8.csv")))
save("white_1986_whole", *from_edges(need("aconnectome_white_1986_whole.csv"), canon))


# ---- Cook 2019（mat；名字排序并集。数量一致性 2026-09-15 已校验 454=454/469=469）----
def mat_names(v):
    out_names = []
    for x in np.asarray(v).ravel():
        if isinstance(x, str):
            out_names.append(x.strip())
        elif isinstance(x, np.ndarray) and x.size:
            out_names.append(str(x.ravel()[0]).strip())
    return out_names


import zipfile

def cook_dir():
    """定位 Cook 2019 的两张 .mat：优先 cook2019/ 目录，其次 zip（内容寻址缓存里是 data）。"""
    d = os.path.join(raw, "cook2019")
    if os.path.isfile(os.path.join(d, "GHermChem.mat")):
        print(f"[setup-evaluator] Cook 2019 源: {d}")
        return d
    for zname in ("cook2019_matlab_ready.zip",):
        z = os.path.join(raw, zname)
        if os.path.isfile(z):
            ex = os.path.join(raw, "_cook_unzip")
            os.makedirs(ex, exist_ok=True)
            with zipfile.ZipFile(z) as zf:
                zf.extractall(ex)
            for root, _dirs, files in os.walk(ex):
                if "GHermChem.mat" in files and "GHermElec_Sym.mat" in files:
                    print(f"[setup-evaluator] Cook 2019 源: {z}（解包到 {root}）")
                    return root
            raise SystemExit(f"[setup-evaluator] {z} 内未找到两张 .mat")
    raise SystemExit(f"[setup-evaluator] 缺 Cook 2019 数据：既无 cook2019/，也无 cook2019_matlab_ready.zip 于 {raw}")


CDIR = cook_dir()
mats, allnames = {}, set()
for fn, tag in (("GHermChem.mat", "chem"), ("GHermElec_Sym.mat", "elec")):
    m = sio.loadmat(os.path.join(CDIR, fn))
    A = m[[k for k in m if k.startswith("A") and hasattr(m[k], "nnz")][0]].toarray()
    names = sorted({x for k in m if not k.startswith("__") and not hasattr(m[k], "nnz")
                    for x in mat_names(m[k])})
    assert len(names) == A.shape[0], f"{fn}: 名字数 {len(names)} != 矩阵 {A.shape[0]}"
    mats[tag] = (A, names)
    allnames |= set(names)

nodes = sorted(allnames & canon)
pos = {x: i for i, x in enumerate(nodes)}
Ac = np.zeros((len(nodes), len(nodes)), dtype=np.uint8)
for tag in ("chem", "elec"):
    Mx, names = mats[tag]
    idx = {x: k for k, x in enumerate(names)}
    sub = Mx[np.ix_([idx[x] for x in nodes], [idx[x] for x in nodes])] > 0
    # GHermChem.mat 的化学突触是**有向**的（pre→post）；题面声明 adjacency 是
    # "chemical and electrical synapses unioned, max(A, A^T) symmetrised" 的无向矩阵，
    # 故这里逐源矩阵即对称化——与 from_edges() 对 witvliet/white 的双向加边一致。
    Ac |= sub.astype(np.uint8)
    Ac |= sub.T.astype(np.uint8)
# 自突触不是连接组边（from_edges() 用 pre != post 排除的也是这一类）。
np.fill_diagonal(Ac, 0)
save("cook_2019", nodes, Ac)
PY

echo "[setup-evaluator] private eval data written to $OUT"
echo "  use this absolute path as BPB_PRIVATE_EVAL_DIR for isolated scoring"
