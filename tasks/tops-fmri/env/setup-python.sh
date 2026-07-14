#!/usr/bin/env bash
# Create the project-local, pinned Python environment used by tops-fmri.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PYTHON_BIN="${BPB_PYTHON:-python3}"
VENV_DIR="${BPB_VENV_DIR:-$REPO_ROOT/.venv}"
REQUIREMENTS="$SCRIPT_DIR/requirements.txt"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python interpreter not found: $PYTHON_BIN" >&2
  echo "Install CPython 3.10-3.13 or set BPB_PYTHON=/absolute/path/to/python." >&2
  exit 1
fi

if ! "$PYTHON_BIN" - <<'PY'
import sys
if not ((3, 10) <= sys.version_info[:2] <= (3, 13)):
    print(
        f"Unsupported Python {sys.version.split()[0]}; tops-fmri supports CPython 3.10-3.13.",
        file=sys.stderr,
    )
    raise SystemExit(1)
PY
then
  exit 1
fi

VENV_PYTHON="$VENV_DIR/bin/python"
if [ -x "$VENV_PYTHON" ]; then
  echo "Reusing virtual environment: $VENV_DIR"
else
  echo "Creating virtual environment with $($PYTHON_BIN -c 'import sys; print(sys.executable)')"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

if ! "$VENV_PYTHON" -c 'import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] <= (3, 13) else 1)'; then
  echo "The existing environment at $VENV_DIR does not use CPython 3.10-3.13." >&2
  echo "Remove that environment or choose another BPB_VENV_DIR." >&2
  exit 1
fi

# python.org macOS builds can be installed before their bundled certificate
# helper has populated OpenSSL's CA file. The system CA bundle is a secure
# fallback; this does not disable verification or trust arbitrary hosts.
if [ -z "${SSL_CERT_FILE:-}" ] && [ -f /etc/ssl/cert.pem ]; then
  DEFAULT_CA="$($VENV_PYTHON -c 'import ssl; print(ssl.get_default_verify_paths().cafile or "")')"
  if [ -z "$DEFAULT_CA" ] || [ ! -f "$DEFAULT_CA" ]; then
    export SSL_CERT_FILE=/etc/ssl/cert.pem
    echo "Using system CA bundle: $SSL_CERT_FILE"
  fi
fi

INSTALL_LOG="$(mktemp)"
trap 'rm -f "$INSTALL_LOG"' EXIT
if ! "$VENV_PYTHON" -m pip install --disable-pip-version-check -r "$REQUIREMENTS" 2>&1 | tee "$INSTALL_LOG"; then
  echo >&2
  echo "Python dependency installation failed." >&2
  echo "Interpreter: $VENV_PYTHON" >&2
  echo "Requirements: $REQUIREMENTS" >&2
  if grep -Eqi 'CERTIFICATE_VERIFY_FAILED|certificate verify failed|unable to get local issuer certificate' "$INSTALL_LOG"; then
    echo "Cause: Python TLS/CA validation failed." >&2
    echo "Repair the Python certificate store; do not use --trusted-host or disable TLS." >&2
  elif grep -Eqi 'proxy|timed out|temporary failure|network is unreachable|connection (refused|reset)' "$INSTALL_LOG"; then
    echo "Cause: PyPI is unreachable through the current network/proxy settings." >&2
    echo "Set https_proxy and http_proxy to an HTTP proxy, then rerun this script." >&2
  fi
  echo "See the Python troubleshooting section in tasks/tops-fmri/README.md." >&2
  exit 1
fi

"$VENV_PYTHON" - <<'PY'
import numpy
import scipy
import sklearn
print(f"Ready: numpy={numpy.__version__}, scipy={scipy.__version__}, scikit-learn={sklearn.__version__}")
PY

echo "Activate with: source \"$VENV_DIR/bin/activate\""
