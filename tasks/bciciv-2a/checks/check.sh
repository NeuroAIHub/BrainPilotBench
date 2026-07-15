#!/bin/bash
# checks/check.sh —— exec-script grader for bciciv-2a.
# 契约:cwd = run bundle dir(agent 产物在 ./artifacts/);sha:BPB_BCI2A_PRIVATE_EVAL_DIR
# 指向一个 workspace 外的 scorer-only 目录,里边有 train_gdf/、test_gdf/、
# true_labels/、manifests/、get_subject_data.py。
# 输出:>>>>> BPB_SCORES / <<<<< BPB_SCORES 之间一行扁平 {string:number} JSON。
# 缺产物 / 数据 / 训练崩了 → 不发哨兵 → unscored(never 0)。
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not available; cannot run bciciv-2a evaluator" >&2
  exit 0
fi

# 私有目录查找顺序:
#   1) 环境变量 BPB_BCI2A_PRIVATE_EVAL_DIR
#   2) $PWD/private_eval(仅 Oracle 门用——solution.sh 造在 bundle 本地)
if [ -z "${BPB_BCI2A_PRIVATE_EVAL_DIR:-}" ]; then
  if [ -d "$PWD/private_eval/train_gdf" ] && [ -d "$PWD/private_eval/test_gdf" ] && [ -d "$PWD/private_eval/true_labels" ]; then
    export BPB_BCI2A_PRIVATE_EVAL_DIR="$PWD/private_eval"
  fi
fi

# Oracle 模式:solution.sh 会 touch 一个 sentinel 文件,让 evaluate_external.py
# 跳过 GPU 训练直接吐 chance-level sentinel(120 秒 validate 沙箱训不完 9 个 subject)。
oracle_flag=()
if [ -f "$PWD/.bpb_oracle_mode" ]; then
  oracle_flag=(--oracle-mode)
fi

python3 "$script_dir/evaluate_external.py" "$PWD" "${oracle_flag[@]}"
