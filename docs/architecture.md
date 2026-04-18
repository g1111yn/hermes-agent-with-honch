# Architecture

## First-Run Topology

- Host:
  - Hermes Agent
  - Hermes API server
  - Hermes model proxy
- Containers:
  - wechat-gateway
  - honcho-api
  - honcho-deriver
  - postgres
  - redis
  - caddy

## Data Flow

1. The WeChat bridge posts a normalized message event to `wechat-gateway`.
2. `wechat-gateway` calls the host Hermes API server at `/v1/responses`.
3. Hermes loads the active role profile and queries Honcho memory.
4. Hermes calls the selected provider through its native provider stack.
5. Honcho uses the host Hermes model proxy for dialectic and embeddings.
6. Hermes returns the final user-facing text.
7. `wechat-gateway` converts the result into 1-3 outbound message units.

## Packaging Rules

- Hermes customizations are stored as a pinned upstream commit plus a patch file.
- Role assets live under `roles/<role-id>/`.
- Container-only services read env from `deploy/.env.*`.
- Host Hermes runtime keeps its own auth, config, and profiles on the server.
