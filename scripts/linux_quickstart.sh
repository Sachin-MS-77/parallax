#!/usr/bin/env bash
set -Eeuo pipefail

# One-command connected Linux/Kali demo setup. It never changes APT sources or
# deletes an existing case; host prerequisites remain explicit and reversible.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
PYTHON_BIN="${PYTHON_BIN:-python3}"
DATA_DIR="${PARALLAX_DATA_DIR:-data/linux-demo}"
PORT="${PARALLAX_PORT:-8765}"

if ! "$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3,11)' 2>/dev/null; then
  printf 'Python 3.11+ is required. Try PYTHON_BIN=python3.12 scripts/linux_quickstart.sh\n' >&2
  exit 2
fi
if ! "$PYTHON_BIN" -c 'import venv' 2>/dev/null; then
  version="$($PYTHON_BIN -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  printf 'Missing Python venv support. Install it once, then rerun:\n' >&2
  printf '  sudo apt-get install --no-upgrade -y python%s-venv python3-pip\n' "$version" >&2
  exit 2
fi

PIP_NO_CACHE_DIR=1 bash scripts/install.sh
"$ROOT_DIR/.venv/bin/python" -m pytest -q

if [[ -e "$DATA_DIR/case.sqlite" ]]; then
  DATA_DIR="${DATA_DIR}-$(date -u +%Y%m%d-%H%M%S)"
  printf 'Existing case preserved; using %s\n' "$DATA_DIR"
fi
"$ROOT_DIR/.venv/bin/parallax" demo --data "$DATA_DIR" --entities "${PARALLAX_ENTITIES:-160}"
printf '\nPARALLAX is ready at http://127.0.0.1:%s\n' "$PORT"
exec "$ROOT_DIR/.venv/bin/parallax" serve --data "$DATA_DIR" --port "$PORT"
