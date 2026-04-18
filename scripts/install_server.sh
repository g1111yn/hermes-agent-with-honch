#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_ROOT="${TARGET_ROOT:-$ROOT}"
SERVICE_USER="${SERVICE_USER:-${SUDO_USER:-$USER}}"
START_SERVICES=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target-root)
      TARGET_ROOT="${2:?missing target root}"
      shift 2
      ;;
    --service-user)
      SERVICE_USER="${2:?missing service user}"
      shift 2
      ;;
    --start)
      START_SERVICES=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

mkdir -p \
  "$TARGET_ROOT/deploy/host" \
  "$TARGET_ROOT/data/wechat-gateway" \
  "$TARGET_ROOT/runtime" \
  "$TARGET_ROOT/server-state"

copy_if_missing() {
  local src="$1"
  local dst="$2"
  if [[ ! -f "$dst" ]]; then
    cp "$src" "$dst"
    echo "Created $dst from template"
  fi
}

copy_if_missing "$ROOT/deploy/.env.shared.example" "$TARGET_ROOT/deploy/.env.shared"
copy_if_missing "$ROOT/deploy/.env.interface.example" "$TARGET_ROOT/deploy/.env.interface"
copy_if_missing "$ROOT/deploy/.env.honcho.example" "$TARGET_ROOT/deploy/.env.honcho"
copy_if_missing "$ROOT/deploy/.env.providers.example" "$TARGET_ROOT/deploy/.env.providers"
copy_if_missing "$ROOT/deploy/host/hermes-host.env.example" "$TARGET_ROOT/deploy/host/hermes-host.env"

install -m 0644 "$ROOT/deploy/systemd/hermes-agent@.service" /etc/systemd/system/hermes-agent@.service
install -m 0644 "$ROOT/deploy/systemd/hermes-model-proxy@.service" /etc/systemd/system/hermes-model-proxy@.service
systemctl daemon-reload

if [[ $START_SERVICES -eq 1 ]]; then
  systemctl enable --now "hermes-agent@${SERVICE_USER}.service" "hermes-model-proxy@${SERVICE_USER}.service"
else
  systemctl enable "hermes-agent@${SERVICE_USER}.service" "hermes-model-proxy@${SERVICE_USER}.service"
fi

cat <<EOF
Server install scaffolding complete.

Target root:   $TARGET_ROOT
Service user:  $SERVICE_USER

Next steps:
1. Review and fill:
   - $TARGET_ROOT/deploy/.env.shared
   - $TARGET_ROOT/deploy/.env.interface
   - $TARGET_ROOT/deploy/.env.honcho
   - $TARGET_ROOT/deploy/.env.providers
   - $TARGET_ROOT/deploy/host/hermes-host.env
2. Run:
   $TARGET_ROOT/scripts/setup_host_runtime.sh
3. Import a role:
   $TARGET_ROOT/scripts/import_role_bundle.sh caleb
4. Start containers:
   make stack-up
EOF
