#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ is required"'
"$PYTHON_BIN" -m venv .venv
if [[ "${1:-}" == "--offline" ]]; then
  WHEELS="${2:?Usage: bash scripts/install.sh --offline /absolute/path/to/wheelhouse}"
  .venv/bin/python -m pip install --no-index --find-links "$WHEELS" 'chimera-offline[test]==0.2.0'
else
  .venv/bin/python -m pip install --upgrade pip
  if [[ "$(uname -s)" == "Linux" ]]; then
    .venv/bin/python -m pip install 'torch>=2.5,<3' --index-url https://download.pytorch.org/whl/cpu
  fi
  .venv/bin/python -m pip install '.[test]'
fi
printf '\nInstalled CHIMERA. Activate with: source .venv/bin/activate\n'
printf 'Start a fresh demo: chimera demo --data data/my-demo --entities 160\n'
printf 'Open dashboard: chimera serve --data data/my-demo --port 8765\n'
