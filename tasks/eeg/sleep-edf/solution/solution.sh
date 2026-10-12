#!/bin/bash
# solution/solution.sh —— Oracle 参考解:造一份"能让 check.sh 完整跑通"的最小 bundle。
#
# 为什么不真训:validate 的 Oracle 沙箱硬限 120s(src/validate.ts),训练
# 14 个 subject 的 sleep-edf(数万个 30 s epoch)在 A10 上要 20-40 min;
# Oracle 门只验证 grader pipeline 能不能产出指标(数值意义不看)。
#
# cwd = oracle bundle 目录;产物在 ./artifacts/;写一个 .bpb_oracle_mode
# sentinel 让 evaluate_external.py 跳过 GPU 训练直接吐 chance-level scores。
set -euo pipefail

mkdir -p artifacts/EEG_sleep

# ============ 1. Oracle sentinel ============
# check.sh 见到这个文件就给 evaluate_external.py 加 --oracle-mode
touch .bpb_oracle_mode

# ============ 2. artifacts/EEG_sleep/sleep_agent_model.py —— 最小合法 SleepAgentModel ============
# 在 --oracle-mode 里其实不会真被 import,但留一份合法的模块以便 non-oracle
# 手动跑管线时也不炸。
cat > artifacts/EEG_sleep/sleep_agent_model.py <<'PY'
"""Oracle placeholder SleepAgentModel — minimal but contract-valid."""
import torch
import torch.nn as nn


class SleepAgentModel(nn.Module):
    """Tiny (Conv1d → BN → ReLU → GAP → Linear) baseline, chance-level by design."""

    def __init__(self) -> None:
        super().__init__()
        self.conv = nn.Conv1d(1, 16, kernel_size=51, padding=25)
        self.bn = nn.BatchNorm1d(16)
        self.act = nn.ReLU(inplace=True)
        self.pool = nn.AdaptiveAvgPool1d(1)
        self.fc = nn.Linear(16, 5)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (B, 1, 3000) → (B, 16, 3000) → (B, 16, 1) → (B, 16) → (B, 5)
        h = self.act(self.bn(self.conv(x)))
        h = self.pool(h).squeeze(-1)
        return self.fc(h)
PY

# ============ 3. workspace 侧 report(expected_artifacts 契约) ============
cat > report.md <<'MD'
# Oracle placeholder report — sleep-edf

Synthesized by `solution/solution.sh` to exercise the artifact contract and
the exec-script grader. `.bpb_oracle_mode` short-circuits
`evaluate_external.py`, which emits chance-level scores so the grader
pipeline can be verified inside the validate sandbox's 120 s budget. Not
a real model; do not interpret these numbers scientifically.
MD

echo "oracle bundle assembled:"
echo "  artifacts/EEG_sleep/sleep_agent_model.py  (minimal but valid SleepAgentModel)"
echo "  .bpb_oracle_mode                          (tells check.sh to skip GPU training)"
echo "  report.md"
