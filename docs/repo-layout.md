# Repo Layout

## Current Deployment Path

These directories are the active distribution layout:

- `apps/wechat-gateway`
  - concrete WeChat interface layer
  - Gewechat-style callback bridge
  - Hermes API forwarding
- `deploy`
  - Docker Compose stack
  - env templates
  - Caddy config
  - systemd units
- `roles`
  - role bundles for import
- `vendor/hermes-agent`
  - upstream lock + Hermes patch bundle
- `scripts`
  - bootstrap, runtime setup, server install, role import, verification, patch refresh
- `docs`
  - deployment and architecture docs
- `database`
  - shared initialization SQL for Honcho Postgres

## Runtime State

These are local/generated state paths and are not the distribution source:

- `data/wechat-gateway`
- `data/users`
- `data/tts`

## Legacy Material

Everything under `legacy/` is preserved reference material from the local PoC phase:

- `legacy/src/hermes_poc`
- `legacy/fixtures`
- `legacy/assets`
- `legacy/role_assets`
- `legacy/docker-compose.yml`
- `legacy/.env.example`
- `legacy/.env.honcho`
- `legacy/honcho_service`

Use it only for historical reference or local smoke tests.
