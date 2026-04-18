# Hermes Persona Server Distribution

This repository is now the distribution repo for a single-node overseas Linux
deployment of your Hermes + Honcho + WeChat stack.

The deployment model is intentionally **semi-containerized**:

- host services:
  - Hermes Agent
  - Hermes API server / model runtime
  - provider auth (Anthropic OAuth, API keys, Codex OAuth, other Hermes-native providers)
- Docker Compose services:
  - wechat-gateway
  - honcho-api
  - honcho-deriver
  - postgres
  - redis
  - caddy

## Repo Layout

- `apps/wechat-gateway`
  normalized WeChat interface service that forwards inbound bridge events to Hermes's API server
- `deploy`
  compose stack, reverse proxy config, env templates, and systemd units
- `roles`
  importable role bundles
- `vendor/hermes-agent/patches`
  patch bundle for the customized Hermes build
- `scripts`
  bootstrap, role import, and verification helpers
- `docs`
  deployment and architecture notes
- `legacy`
  archived local PoC assets kept only for reference and smoke tests

## Hermes Packaging Strategy

This repo does **not** vendor the full 800MB local Hermes worktree. Instead it
ships:

- the pinned upstream commit
- a binary-safe patch bundle containing your local Hermes customizations
- overlay files for runtime modules added outside tracked patch state
- bootstrap scripts that materialize the customized Hermes tree on a fresh host

This keeps the repo lightweight while preserving reproducibility.

See:

- [vendor/hermes-agent/README.md](/Users/sleepy_gyn/Documents/项目：Hermes with honch/vendor/hermes-agent/README.md)
- [scripts/bootstrap_hermes_vendor.sh](/Users/sleepy_gyn/Documents/项目：Hermes with honch/scripts/bootstrap_hermes_vendor.sh)

## Default Runtime Topology

1. `wechat-gateway` receives a normalized inbound message event.
2. `wechat-gateway` calls the host Hermes API server.
3. Hermes runs the active role profile and talks to Honcho.
4. Honcho calls the host Hermes model proxy for dialectic/embedding work.
5. Hermes returns the final user-facing messages.
6. `wechat-gateway` returns chunked outbound messages to the bridge layer.

## Current WeChat Bridge Support

`apps/wechat-gateway` now includes a concrete `gewechat`-style bridge driver:

- receives bridge callbacks at `/bridges/gewechat/callback`
- deduplicates inbound message IDs
- parses direct and group text messages
- forwards normalized text into Hermes
- sends `1/2/3` chunked text replies back through the bridge HTTP API

This is enough for first-pass text messaging on a Linux server. Voice, image,
and richer bridge features remain follow-up work.

## Quick Start

1. Bootstrap Hermes on the host:

```bash
make host-runtime
```

2. Install env templates and systemd scaffolding:

```bash
make server-install
```

3. Fill the generated env files under `deploy/` and `deploy/host/`.

4. Import the role bundle:

```bash
./scripts/import_role_bundle.sh caleb
```

5. Start the host services:

```bash
sudo systemctl start hermes-agent@$USER.service hermes-model-proxy@$USER.service
```

6. Start the container stack:

```bash
make stack-up
```

7. Verify:

```bash
make stack-ps
python3 ./scripts/verify_server_stack.py
```

## Deployment Docs

- [docs/server-deployment.md](/Users/sleepy_gyn/Documents/项目：Hermes with honch/docs/server-deployment.md)
- [docs/architecture.md](/Users/sleepy_gyn/Documents/项目：Hermes with honch/docs/architecture.md)
- [docs/repo-layout.md](/Users/sleepy_gyn/Documents/项目：Hermes with honch/docs/repo-layout.md)

## Notes

- Anthropic OAuth is the default first-run path, but the deployment layout also
  supports API keys, Codex OAuth, and Hermes-native provider switching.
- Inside `hermes chat`, `/model` now supports:
  - switching between already configured providers
  - setting up an official Hermes-native provider in-session
  - adding a third-party endpoint with `base_url + api_key + protocol`
  - both OpenAI-compatible and Anthropic-compatible custom relays
- `apps/wechat-gateway` is intentionally bridge-agnostic. It is the place where
  iPad-protocol style bridges can be integrated without coupling bridge logic to
  Hermes itself.
- The old local PoC is preserved under [legacy/](/Users/sleepy_gyn/Documents/项目：Hermes with honch/legacy/README.md), but the
  main deployment path is now the semi-containerized server layout in `deploy/`.
