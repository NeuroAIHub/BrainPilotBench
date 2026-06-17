#!/bin/bash
# 示例 grader:检查 artifacts/ 下有 .csv,数据行数(去表头)是否为 3。
# 契约:在 >>>>> BPB_SCORES / <<<<< BPB_SCORES 之间输出一行扁平 number JSON。
# ⚠️ NOP 语义:无产物(空提交)时**不输出哨兵**——让评分回 unscored,而非"啥都不干也出指标"。
# cwd = run bundle 目录;产物在 ./artifacts/ 下。
set -euo pipefail
csv=$(ls artifacts/*.csv 2>/dev/null | head -1 || true)
if [ -z "$csv" ]; then
  # 空提交/无 CSV:不发哨兵 → 评分 unscored(NOP 门要求出不了指标)。
  echo "no csv artifact found; emitting no score" >&2
  exit 0
fi
rows=$(($(wc -l < "$csv") - 1))   # 去表头
ok=0
[ "$rows" -eq 3 ] && ok=1
echo ">>>>> BPB_SCORES"
echo "{\"rows\": ${rows}, \"rows_ok\": ${ok}}"
echo "<<<<< BPB_SCORES"
