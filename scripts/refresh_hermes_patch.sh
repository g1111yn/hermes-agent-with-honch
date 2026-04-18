#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="${1:-$HOME/.hermes/hermes-agent}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PATCH_PATH="$ROOT/vendor/hermes-agent/patches/0001-hermes-local-customizations.patch"

git -C "$SOURCE_DIR" diff --binary > "$PATCH_PATH"
echo "Refreshed patch bundle at $PATCH_PATH"
