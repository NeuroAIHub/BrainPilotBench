#!/bin/bash
# checks/check.sh —— exec-script grader for tops-fmri.
# 契约:cwd = run bundle dir(agent 产物在 ./artifacts/);sha:BPB_TOPS_PRIVATE_EVAL_DIR
# 指向一个 workspace 外的 scorer-only 目录,里边有 features/ 和 labels/。
# 输出:>>>>> BPB_SCORES / <<<<< BPB_SCORES 之间一行扁平 {string:number} JSON。
# 缺产物 / features / labels → 不发哨兵 → unscored(never 0)。
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not available; cannot run tops-fmri evaluator" >&2
  exit 0
fi

# 私有目录查找顺序:
#   1) 环境变量 BPB_TOPS_PRIVATE_EVAL_DIR
#   2) $PWD/private_eval(仅 Oracle 门用——solution.sh 造在 bundle 本地)
if [ -z "${BPB_TOPS_PRIVATE_EVAL_DIR:-}" ]; then
  if [ -d "$PWD/private_eval/features" ] && [ -d "$PWD/private_eval/labels" ]; then
    export BPB_TOPS_PRIVATE_EVAL_DIR="$PWD/private_eval"
  fi
fi

python3 "$script_dir/evaluate_external.py" "$PWD"
