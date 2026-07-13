#!/bin/bash
# solution/solution.sh —— Oracle 参考解:造一份"能让 check.sh 完整跑通"的最小 bundle。
#
# 为什么不真训:validate 的 Oracle 沙箱硬限 120s(src/validate.ts),Study3 训练完全跑不完;
# Oracle 门只验证 grader pipeline 能不能产出指标(数值意义不看),不验证信号质量。
#
# cwd = oracle bundle 目录;产物在 ./artifacts/;私有 dummy 数据放在 ./private_eval/
# (evaluate_external.py 的第 2 优先级搜索路径)。这样 validate 时不依赖 env/setup.sh 也能跑。
set -euo pipefail

mkdir -p artifacts/scripts artifacts/models private_eval/features private_eval/labels

# ============ 1. dummy Study4/Study5 features + labels ============
# 每 condition/site 造 3 个样本(pearson_r 最少 3 个,auc 需要至少一个正/负),shape 与
# 真实一致(38781 edge)。数值取标准正态,label 一半正一半负;权重全零 → response 全 0
# → r ≈ 0(clip 到 0),auc ≈ 0.5;聚合 score ≈ 0.25。> gate.oracleMin(1)? 不,是"unscored
# 反面":Oracle 需要 exec scorer 产出指标(即 !unscored),数值无所谓。
python3 - <<'PY'
import numpy as np, json
from pathlib import Path

rng = np.random.default_rng(42)
NED = 38781  # 279 * 278 / 2

# Study4: 4 conditions × 3 samples;label 用小整数,per-condition std > 0 让 pearson_r 定义
np.savez(
    "private_eval/features/study4_features.npz",
    SBP_SP=rng.standard_normal((3, NED)).astype(np.float32),
    SBP_REST=rng.standard_normal((3, NED)).astype(np.float32),
    CBP_SP=rng.standard_normal((3, NED)).astype(np.float32),
    CBP_REST=rng.standard_normal((3, NED)).astype(np.float32),
)
np.savez(
    "private_eval/labels/study4_labels.npz",
    SBP_SP=np.array([1.0, 2.0, 3.0]),
    SBP_REST=np.array([2.0, 3.0, 4.0]),
    CBP_SP=np.array([3.0, 4.0, 5.0]),
    CBP_REST=np.array([1.0, 3.0, 5.0]),
)
# Study5: 2 sites × 3 samples;label 用 0/1(每 site 至少一个正一个负 → auc 有定义)
np.savez(
    "private_eval/features/study5_features.npz",
    JP=rng.standard_normal((3, NED)).astype(np.float32),
    UK=rng.standard_normal((3, NED)).astype(np.float32),
)
np.savez(
    "private_eval/labels/study5_labels.npz",
    JP=np.array([0, 1, 0]),
    UK=np.array([1, 0, 1]),
)

# ============ 2. artifacts/models —— 全零 signature ============
np.savez(
    "artifacts/models/study3_signature_weights.npz",
    w_raw=np.zeros(NED, dtype=np.float32),
    b_raw=np.float32(0.0),
)
Path("artifacts/models/signature_manifest.json").write_text(json.dumps({
    "n_rois": 279,
    "n_edges": NED,
    "edge_order": "source_feature_order_preserved_but_roi_mapping_unverified",
    "input_transform": "none",
    "response_direction": "higher_means_more_pain",
    "training_method": "oracle_placeholder_zero_weights",
    "study3_split_strategy": "n/a (oracle placeholder)",
    "weights_are_averaged_over_splits_or_seeds": False,
    "_oracle_note": "synthetic zero-weight signature for validate gate; NOT a real model",
}, indent=2))
PY

# ============ 3. artifacts/scripts/apply_signature.py ============
# 只依赖 numpy 的最小推理脚本:遵守 prompt 里的严格线性契约 y = x @ w_raw + b_raw。
# 输入 features 的 NaN 用 nan_to_num(0) 处理(prompt 允许的固定规则)。
cat > artifacts/scripts/apply_signature.py <<'PY'
#!/usr/bin/env python3
"""Minimal Oracle-side inference: y = fisher_z(x) @ w_raw + b_raw (with w=0 → y=0)."""
from __future__ import annotations
import argparse, csv, sys
from pathlib import Path
import numpy as np

STUDY4_CONDITIONS = ["SBP_SP", "SBP_REST", "CBP_SP", "CBP_REST"]
STUDY5_SITES = ["JP", "UK"]


def load_signature(model_dir: Path):
    z = np.load(model_dir / "study3_signature_weights.npz")
    w = np.asarray(z["w_raw"], dtype=np.float64).reshape(-1)
    b = float(np.asarray(z["b_raw"]).reshape(-1)[0])
    return w, b


def infer(features_dir: Path, w: np.ndarray, b: float):
    s4 = np.load(features_dir / "study4_features.npz")
    s5 = np.load(features_dir / "study5_features.npz")
    out4 = {}
    for c in STUDY4_CONDITIONS:
        x = np.asarray(s4[c], dtype=np.float64)
        x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
        out4[c] = x @ w + b
    out5 = {}
    for s in STUDY5_SITES:
        x = np.asarray(s5[s], dtype=np.float64)
        x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
        out5[s] = x @ w + b
    return out4, out5


def write_csv(path: Path, group_col: str, groups: dict):
    with path.open("w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow([group_col, "sample_id", "signature_response"])
        for g, arr in groups.items():
            for i, v in enumerate(arr):
                wr.writerow([g, i, float(v)])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-features-dir", required=True)
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    w, b = load_signature(Path(a.model_dir))
    out4, out5 = infer(Path(a.eval_features_dir), w, b)
    out_dir = Path(a.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(out_dir / "study4_predictions.csv", "condition", out4)
    write_csv(out_dir / "study5_predictions.csv", "site", out5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY
chmod +x artifacts/scripts/apply_signature.py

# ============ 4. workspace 侧 report + results 占位(expected_artifacts 契约) ============
cat > report.md <<'MD'
# Oracle placeholder report — tops-fmri

Synthesized by `solution/solution.sh` to exercise the artifact contract and
the exec-script grader. Not a real model; do not interpret these numbers
scientifically.
MD

mkdir -p results
python3 - <<'PY'
import json, pathlib
pathlib.Path("results/edge_order_validation.json").write_text(json.dumps({
    "candidates_checked": ["oracle_placeholder"],
    "chosen": "source_feature_order_preserved_but_roi_mapping_unverified",
    "roi_pair_mapping_reliable": False,
    "_note": "oracle placeholder — no real edge-order check performed"
}, indent=2))
pathlib.Path("results/model_card.json").write_text(json.dumps({
    "final_model": "oracle_placeholder_zero_weights",
    "input_transform": "none",
    "n_edges": 38781,
    "study3_split_seed_or_seeds": [42],
    "study3_overall_r": 0.0,
    "study3_within_subject_mean_r": 0.0,
    "study3_caps_vs_rest_accuracy": 0.5,
    "signature_weight_file": "models/study3_signature_weights.npz",
    "inference_script": "scripts/apply_signature.py",
    "_oracle_note": "placeholder"
}, indent=2))
PY

echo "oracle bundle assembled:"
echo "  artifacts/scripts/apply_signature.py + artifacts/models/{weights,manifest}"
echo "  private_eval/features/{study4,study5}_features.npz + labels/*"
echo "  report.md + results/{edge_order_validation.json, model_card.json}"
