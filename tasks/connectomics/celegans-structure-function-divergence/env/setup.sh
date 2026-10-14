#!/bin/bash
# env/setup.sh —— 数据铺设总入口。框架按角色调用：
#   prepareWorkspace() 会以 `setup.sh --role agent` 调用，cwd 已切到 Agent 工作区。
#   evaluator 侧由 maintainer 以 `--role evaluator` 调用，铺私有数据到独立目录。
#
# 关键约束：
#   - agent 角色只能铺 scope: public 的数据。私有数据铺进工作区会让
#     workflow.ts:assertAgentDataBoundary 在 Agent 启动前直接抛错。
#   - 幂等：重复调用不应重复下载。
set -euo pipefail

ROLE="agent"
while [ $# -gt 0 ]; do
  case "$1" in
    --role) ROLE="${2:-agent}"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TASK_DIR="$(cd "$HERE/.." && pwd)"

case "$ROLE" in
  agent)     exec bash "$TASK_DIR/env/setup-agent.sh" ;;
  evaluator) exec bash "$TASK_DIR/env/setup-evaluator.sh" ;;
  *) echo "unknown role: $ROLE (expect agent|evaluator)" >&2; exit 2 ;;
esac
