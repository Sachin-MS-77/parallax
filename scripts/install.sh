#!/usr/bin/env bash
set -Eeuo pipefail

# PARALLAX bootstrap. It uses the repository-local .venv and disables pip's
# cache so interrupted installs do not consume disk and leave a stale venv.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="$ROOT_DIR/.venv"
MIN_FREE_KB="${PARALLAX_MIN_FREE_KB:-2097152}" # 2 GiB headroom for torch/build temp

on_error() {
  local code=$?
  printf '\nPARALLAX installation stopped (exit %s).\n' "$code" >&2
  printf 'Check space with: df -h .\n' >&2
  printf 'Retry after cleanup with: PIP_NO_CACHE_DIR=1 bash scripts/install.sh\n\n' >&2
  exit "$code"
}
trap on_error ERR

usage() {
  cat <<'EOF'
Usage:
  bash scripts/install.sh
  bash scripts/install.sh --offline /absolute/path/to/wheelhouse

Environment:
  PYTHON_BIN=python3.12       Select the Python executable.
  PARALLAX_MIN_FREE_KB=...   Override the 2 GiB disk preflight when appropriate.
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then usage; exit 0; fi
MODE="online"
WHEELS=""
if [[ "${1:-}" == "--offline" ]]; then
  MODE="offline"
  WHEELS="${2:?Usage: bash scripts/install.sh --offline /absolute/path/to/wheelhouse}"
  [[ -d "$WHEELS" ]] || { printf 'Wheelhouse does not exist: %s\n' "$WHEELS" >&2; exit 2; }
elif [[ $# -gt 0 ]]; then
  usage >&2
  exit 2
fi

"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ is required (Python 3.12 is recommended on Linux)"'
"$PYTHON_BIN" -c 'import venv' || {
  printf 'Python venv support is missing. On Kali/Debian run: sudo apt-get update && sudo apt-get install -y python3-venv python3-pip\n' >&2
  exit 2
}

if [[ "$(uname -s)" == "Linux" ]]; then
  available_kb="$(df -Pk "$ROOT_DIR" | awk 'NR==2 {print $4}')"
  if [[ -z "$available_kb" || "$available_kb" -lt "$MIN_FREE_KB" ]]; then
    printf 'Insufficient disk space. Available: %s KiB; required: %s KiB.\n' "${available_kb:-unknown}" "$MIN_FREE_KB" >&2
    printf 'Run: df -h .\n' >&2
    printf 'Find large directories: du -xhd1 ~ | sort -h\n' >&2
    printf 'Clear pip downloads: %s -m pip cache purge\n' "$PYTHON_BIN" >&2
    exit 3
  fi
fi

if [[ -x "$VENV_DIR/bin/python" ]]; then
  printf 'Reusing repository environment: %s\n' "$VENV_DIR"
else
  printf 'Creating repository environment: %s\n' "$VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

PIP=("$VENV_DIR/bin/python" -m pip)
export PIP_NO_CACHE_DIR=1
"${PIP[@]}" --disable-pip-version-check install --upgrade pip

if [[ "$MODE" == "offline" ]]; then
  "${PIP[@]}" install --no-index --find-links "$WHEELS" '.[test]'
else
  if [[ "$(uname -s)" == "Linux" ]]; then
    "${PIP[@]}" install --index-url https://download.pytorch.org/whl/cpu 'torch>=2.5,<3'
  fi
  "${PIP[@]}" install '.[test]'
fi

"$VENV_DIR/bin/python" -c 'import parallax, torch; print("PARALLAX import check: ok")'
printf '\nInstalled PARALLAX in %s\n' "$VENV_DIR"
printf 'Activate:  source .venv/bin/activate\n'
printf 'Verify:    python -m pytest -q\n'
printf 'Demo:      parallax demo --data data/demo --entities 160\n'
printf 'Dashboard: parallax serve --data data/demo --port 8765\n'
