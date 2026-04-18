#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <role-id>"
  exit 1
fi

ROLE_ID="$1"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${HERMES_AGENT_ROOT:-$ROOT/runtime/hermes-agent}"
ROLE_SOURCE="$ROOT/roles/$ROLE_ID"

if [[ ! -d "$RUNTIME_DIR" ]]; then
  echo "Hermes runtime not found at $RUNTIME_DIR"
  exit 1
fi

if [[ ! -d "$ROLE_SOURCE" ]]; then
  echo "Role bundle not found at $ROLE_SOURCE"
  exit 1
fi

"$RUNTIME_DIR/venv/bin/python" -m hermes_cli.main profile prepare-role "$ROLE_ID"
"$RUNTIME_DIR/venv/bin/python" -m hermes_cli.main profile apply-role-assets "$ROLE_ID" --source "$ROLE_SOURCE" --reset

echo "Imported role bundle: $ROLE_ID"
