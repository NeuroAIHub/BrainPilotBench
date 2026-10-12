#!/usr/bin/env bash
# 创建本任务固定的 Python 环境（agent 侧与 scorer 侧共用同一个解释器）。
#
# 用法：
#   env/setup-python.sh                      # 默认装到 <repo>/.cache/celegans/venv
#   BPB_VENV_DIR=/abs/path env/setup-python.sh
#   BPB_PYTHON=/abs/path/to/base-python env/setup-python.sh
#
# 官方评测端在容器里跑，解释器由镜像提供；本脚本供本地/发布时重建同一套数值栈。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
PYTHON_BIN="${BPB_PYTHON:-python3}"
VENV_DIR="${BPB_VENV_DIR:-$REPO_ROOT/.cache/celegans/venv}"
REQUIREMENTS="$SCRIPT_DIR/requirements.txt"

# Git Bash(MSYS) 下 bash 内建命令认 /f/... 形式，但**传给原生 python 的实参不会自动
# 转换**——`python -m venv /f/x` 会在 F:\ 下造出 f\x。凡把路径当实参交给原生解释器的
# 地方都要过这一层；Linux/macOS 上无 cygpath，本函数是空操作。
towl() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi; }

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python interpreter not found: $PYTHON_BIN" >&2
  echo "Install CPython 3.12-3.13 or set BPB_PYTHON=/absolute/path/to/python." >&2
  exit 1
fi

if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if (3, 12) <= sys.version_info[:2] <= (3, 13) else 1)'; then
  echo "Unsupported Python: $("$PYTHON_BIN" -c 'import sys; print(sys.version.split()[0])')" >&2
  echo "This task supports CPython 3.12-3.13 with the pinned dependencies." >&2
  exit 1
fi

# venv 的解释器路径：POSIX 是 bin/python，Windows 是 Scripts/python.exe。
venv_python() {
  if [ -x "$VENV_DIR/bin/python" ]; then printf '%s' "$VENV_DIR/bin/python"
  elif [ -x "$VENV_DIR/Scripts/python.exe" ]; then printf '%s' "$VENV_DIR/Scripts/python.exe"
  else printf '%s' ""; fi
}

VENV_PYTHON="$(venv_python)"
if [ -n "$VENV_PYTHON" ]; then
  echo "Reusing virtual environment: $VENV_DIR"
else
  echo "Creating virtual environment with $("$PYTHON_BIN" -c 'import sys; print(sys.executable)')"
  "$PYTHON_BIN" -m venv "$(towl "$VENV_DIR")"
  VENV_PYTHON="$(venv_python)"
fi

if [ -z "$VENV_PYTHON" ]; then
  echo "Could not locate the interpreter inside $VENV_DIR" >&2
  exit 1
fi

INSTALL_LOG="$(mktemp)"
trap 'rm -f "$INSTALL_LOG"' EXIT
install_dependencies() {
  if command -v uv >/dev/null 2>&1; then
    uv pip install --system-certs --python "$(towl "$VENV_PYTHON")" -r "$(towl "$REQUIREMENTS")"
  else
    "$VENV_PYTHON" -m pip install --disable-pip-version-check -r "$(towl "$REQUIREMENTS")"
  fi
}
if ! install_dependencies 2>&1 | tee "$INSTALL_LOG"; then
  echo >&2
  echo "Python dependency installation failed." >&2
  echo "Interpreter: $VENV_PYTHON" >&2
  echo "Requirements: $REQUIREMENTS" >&2
  if grep -Eqi 'certificate verify failed|unable to get local issuer' "$INSTALL_LOG"; then
    echo "Cause: TLS/CA validation failed. Repair the Python certificate store; do not use --trusted-host." >&2
  elif grep -Eqi 'proxy|timed out|temporary failure|connection (refused|reset)' "$INSTALL_LOG"; then
    echo "Cause: PyPI unreachable. Set https_proxy/http_proxy and rerun." >&2
  fi
  exit 1
fi

"$VENV_PYTHON" - <<'PY'
import networkx, numpy, scipy, sklearn
print(
    "Ready: numpy=%s, scipy=%s, scikit-learn=%s, networkx=%s"
    % (numpy.__version__, scipy.__version__, sklearn.__version__, networkx.__version__)
)
PY

echo "Interpreter for this task: $VENV_PYTHON"
echo "Set BPB_PYTHON to that path so env/checks scripts use it."
