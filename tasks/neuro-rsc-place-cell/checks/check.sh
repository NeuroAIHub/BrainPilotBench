#!/bin/bash
# checks/check.sh —— exec-script grader for neuro-rsc-place-cell.
# 契约:cwd = run bundle dir;产物在 ./artifacts/;在 >>>>> BPB_SCORES / <<<<< BPB_SCORES
# 之间输出一行 flat {string:number} JSON。缺产物/关键字段 → 不发哨兵 → unscored(never 0)。
#
# 覆盖 3 项 exec 指标(与 categories.yaml 的 neural-analysis 前 3 个 metric 对齐):
#   place_cell_ratio_ok               位置细胞比例在参考区间内
#   decoding_significance_ok          decoding_significant 布尔与参考一致
#   decoding_error_within_tolerance   real error 相对 shuffle 的改善比例达标
#   score                              上述三项检查的等权均值
#
# 剩下 3 个类别 metric(visualization_quality / trial_bin_analysis / firing_rate_analysis)
# 由同 task.yaml 声明的 rubric-human scorer 负责——填 scoresheet 走人工审核。
set -euo pipefail

summary_path="artifacts/benchmark_summary.json"
if [ ! -f "$summary_path" ]; then
  echo "no benchmark_summary.json in artifacts/; NOP → unscored" >&2
  exit 0
fi

# 用 python 做安全的 JSON 抽字段 + 与参考值容差比对。python3 必备(BPB 未来 docker sandbox
# 也应包);缺 python3 → 报错但不发哨兵,评分回 unscored(明确写出原因方便定位)。
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not available in sandbox; cannot parse summary" >&2
  exit 0
fi

TASK_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ref_path="$TASK_DIR/checks/reference.json"

python3 - "$summary_path" "$ref_path" <<'PY'
import json, math, sys

summary_path, ref_path = sys.argv[1], sys.argv[2]

def _fail(msg):
    print(msg, file=sys.stderr)
    sys.exit(0)  # 不发哨兵 → unscored

try:
    with open(summary_path, encoding="utf-8") as f: s = json.load(f)
    with open(ref_path,     encoding="utf-8") as f: ref = json.load(f)
except Exception as e:
    _fail(f"cannot read/parse json: {e}")

# 抽字段:少一个或类型违反公开 schema 就 unscored,不给隐式类型转换污染榜单的机会。
def _number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{field} must be a JSON number")
    value = float(value)
    if not math.isfinite(value):
        _fail(f"{field} must be finite")
    return value

try:
    ratio = _number(
        s["cross_session_place_cell_stability"]["place_cell_ratio_mean"],
        "place_cell_ratio_mean",
    )
    decoding = s["position_decoding_significance"]
    sig = decoding["decoding_significant"]
    if not isinstance(sig, bool):
        _fail("decoding_significant must be a JSON boolean")
    real = _number(decoding["real_median_decoding_error_cm"], "real_median_decoding_error_cm")
    shuf = _number(decoding["shuffle_median_decoding_error_cm"], "shuffle_median_decoding_error_cm")
except (KeyError, TypeError) as e:
    _fail(f"summary missing required field(s): {e}")

if not 0.0 <= ratio <= 1.0:
    _fail("place_cell_ratio_mean must be between 0 and 1")
if real < 0.0 or shuf < 0.0:
    _fail("decoding errors must be non-negative")

# 1. place cell ratio 在参考区间
pc = ref["place_cell_ratio_mean"]
place_cell_ratio_ok = 1 if (pc["min"] <= ratio <= pc["max"]) else 0

# 2. decoding_significant 布尔一致
decoding_significance_ok = 1 if (sig == ref["decoding_significant_expected"]) else 0

# 3. 解码误差改善幅度达标:1 - real/shuffle >= 冻结门槛;shuffle=0 视作坏样本
if shuf <= 0:
    reduction_ratio = 0.0
else:
    reduction_ratio = 1.0 - (real / shuf)
threshold = float(ref["decoding_improvement_ratio_min"])
decoding_error_within_tolerance = 1 if reduction_ratio >= threshold else 0

score = (
    place_cell_ratio_ok
    + decoding_significance_ok
    + decoding_error_within_tolerance
) / 3.0

out = {
    "place_cell_ratio_ok": place_cell_ratio_ok,
    "decoding_significance_ok": decoding_significance_ok,
    "decoding_error_within_tolerance": decoding_error_within_tolerance,
    "score": round(score, 6),
    # 附:原始值,方便 leaderboard 之外的分析(不进 category 必备集,不影响门)
    "place_cell_ratio_mean_value": ratio,
    "decoding_error_reduction_ratio_value": round(reduction_ratio, 4),
}
print(">>>>> BPB_SCORES")
print(json.dumps(out))
print("<<<<< BPB_SCORES")
PY
