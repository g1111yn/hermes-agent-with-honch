#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_FILE="$ROOT/vendor/hermes-agent/UPSTREAM.lock"
RUNTIME_DIR="${HERMES_RUNTIME_DIR:-$ROOT/runtime/hermes-agent}"

repo_url="$(grep '^repo=' "$LOCK_FILE" | cut -d'=' -f2-)"
commit_sha="$(grep '^commit=' "$LOCK_FILE" | cut -d'=' -f2-)"
patch_path="$ROOT/$(grep '^patch=' "$LOCK_FILE" | cut -d'=' -f2-)"

rm -rf "$RUNTIME_DIR"
mkdir -p "$(dirname "$RUNTIME_DIR")"

git clone "$repo_url" "$RUNTIME_DIR"
git -C "$RUNTIME_DIR" checkout "$commit_sha"
git -C "$RUNTIME_DIR" apply "$patch_path"

echo "Hermes runtime materialized at $RUNTIME_DIR"
echo "Next step: create its venv and install dependencies."
