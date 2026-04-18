# Legacy PoC

This directory contains the earlier local PoC assets that predate the current
semi-containerized distribution layout.

Included here:

- local PoC runtime under `src/hermes_poc`
- replay fixtures
- old character assets
- old role asset source bundles
- old root-level compose/env files
- old mock Honcho service

The active deployment path is now outside this directory:

- `deploy/`
- `apps/wechat-gateway/`
- `roles/`
- `vendor/hermes-agent/`
- `scripts/`

If you only care about the server-ready distribution, you can ignore `legacy/`.
