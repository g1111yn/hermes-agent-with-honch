#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${HERMES_RUNTIME_DIR:-$ROOT/runtime/hermes-agent}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
INSTALL_EXTRAS="${HERMES_INSTALL_EXTRAS:-web,messaging,cli,honcho}"
FORCE_REBUILD=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force)
      FORCE_REBUILD=1
      shift
      ;;
    --python)
      PYTHON_BIN="${2:?missing python path}"
      shift 2
      ;;
    --extras)
      INSTALL_EXTRAS="${2:?missing extras}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ $FORCE_REBUILD -eq 1 || ! -d "$RUNTIME_DIR" ]]; then
  HERMES_RUNTIME_DIR="$RUNTIME_DIR" "$ROOT/scripts/bootstrap_hermes_vendor.sh"
fi

if [[ ! -f "$RUNTIME_DIR/pyproject.toml" ]]; then
  echo "Hermes runtime not materialized at $RUNTIME_DIR" >&2
  exit 1
fi

if [[ ! -d "$RUNTIME_DIR/venv" ]]; then
  "$PYTHON_BIN" -m venv "$RUNTIME_DIR/venv"
fi

"$RUNTIME_DIR/venv/bin/pip" install --upgrade pip setuptools wheel
"$RUNTIME_DIR/venv/bin/pip" install -e "$RUNTIME_DIR[$INSTALL_EXTRAS]"

echo "Hermes host runtime ready at $RUNTIME_DIR"
echo "Python: $RUNTIME_DIR/venv/bin/python"
echo "CLI:    $RUNTIME_DIR/venv/bin/hermes"
