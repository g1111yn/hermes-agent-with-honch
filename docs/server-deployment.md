# Server Deployment

## Target

- Ubuntu 24.04 LTS
- one overseas VPS
- Docker Compose for the container stack
- systemd for host Hermes services

## Host Steps

1. Install:
   - git
   - python3.12
   - python3.12-venv
   - docker
   - docker compose plugin
2. Clone this repo to `/opt/hermes-persona`
3. Run `sudo ./scripts/install_server.sh --service-user <linux-user>`
4. Run `./scripts/setup_host_runtime.sh`
5. Copy:
   - `deploy/.env.shared.example -> deploy/.env.shared`
   - `deploy/.env.interface.example -> deploy/.env.interface`
   - `deploy/.env.honcho.example -> deploy/.env.honcho`
   - `deploy/.env.providers.example -> deploy/.env.providers`
6. Fill env files
7. Import the role bundle
8. Start host services
9. Run `make stack-up`

## One-Time Bootstrap Commands

```bash
sudo ./scripts/install_server.sh --service-user "$USER"
./scripts/setup_host_runtime.sh
./scripts/import_role_bundle.sh caleb
sudo systemctl start hermes-agent@$USER.service hermes-model-proxy@$USER.service
make stack-up
```

## WeChat Bridge Layer

The first concrete interface-layer target is `gewechat`-style HTTP bridging:

- inbound callback:
  - `POST /bridges/gewechat/callback`
- outbound send:
  - bridge HTTP API at `WECHAT_BRIDGE_API_BASE`
- persisted state:
  - dedupe store under `WECHAT_GATEWAY_STATE_DIR`

Required bridge env keys:

```bash
WECHAT_BRIDGE_NAME=gewechat
WECHAT_BRIDGE_API_BASE=http://bridge-host:2531/v2/api
WECHAT_BRIDGE_APP_ID=your-app-id
WECHAT_BRIDGE_TOKEN=your-callback-token
WECHAT_BRIDGE_CALLBACK_URL=https://your-domain.example/bridges/gewechat/callback
```

Optional:

```bash
WECHAT_BRIDGE_AUTO_REGISTER_CALLBACK=true
```

If enabled, `wechat-gateway` will attempt to register its callback URL with the
bridge on startup.

## Hermes Host Env

Recommended values in `deploy/host/hermes-host.env`:

```bash
API_SERVER_ENABLED=true
API_SERVER_HOST=127.0.0.1
API_SERVER_PORT=8642
API_SERVER_KEY=change-me
HERMES_PROXY_PORT=11435
HERMES_HOME=/opt/hermes-persona/server-state/hermes
```

## Role Import

```bash
./scripts/import_role_bundle.sh caleb
```

## Verification

```bash
make stack-ps
./scripts/verify_server_stack.py
```

## systemd

```bash
sudo ./scripts/install_server.sh --service-user "$USER"
```

The installer:

- copies `hermes-agent@.service`
- copies `hermes-model-proxy@.service`
- enables both units
- creates missing env files from templates

## Provider Strategy

- first run: Anthropic OAuth
- later supported:
  - Anthropic API Key
  - Codex OAuth
  - other Hermes-native providers
  - custom OpenAI-compatible endpoints
  - custom Anthropic-compatible endpoints

## In-Session Model Setup

Once `hermes chat` is running on the host, `/model` is the primary operator UX:

- `/model`
  - switch among configured providers and models
  - open “Set up official provider”
  - open “Add third-party endpoint”
- `/model setup`
  - jump straight into the official provider setup flow
- `/model custom`
  - jump straight into custom endpoint setup

For third-party endpoints, Hermes now prompts for:

- `base_url`
- `api_key`
- protocol family
  - auto-detect
  - OpenAI-compatible
  - Anthropic-compatible
- model name

This keeps the server deployment compatible with:

- Hermes-native official providers
- Codex OAuth
- Anthropic OAuth / API key
- third-party relay URLs without hardcoded vendor assumptions
