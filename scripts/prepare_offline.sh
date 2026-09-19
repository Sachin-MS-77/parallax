#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON_BIN="${PYTHON_BIN:-python3}"
WHEELS="${1:-wheelhouse}"
mkdir -p "$WHEELS"
# Run on the same Linux architecture/Python version as the disconnected target.
if [[ "$(uname -s)" == "Linux" ]]; then
  "$PYTHON_BIN" -m pip download --dest "$WHEELS" 'torch>=2.5,<3' --index-url https://download.pytorch.org/whl/cpu
fi
"$PYTHON_BIN" -m pip wheel --wheel-dir "$WHEELS" --find-links "$WHEELS" '.[test]'
"$PYTHON_BIN" scripts/wheel_manifest.py "$WHEELS"
printf '\nTransfer this project and wheelhouse to the matching offline computer.\n'
