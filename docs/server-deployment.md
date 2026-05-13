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

`wechat-gateway` now supports both:

- native `gewechat`
  - inbound callback: `POST /bridges/gewechat/callback`
  - outbound send: Gewechat HTTP API at `WECHAT_BRIDGE_API_BASE`
- generic HTTP relay
  - inbound callback: `POST /wechat/v1/messages/inbound`
  - outbound send: `POST {WECHAT_BRIDGE_API_BASE}/messages/send`

Persisted state remains the same for both:

- dedupe store under `WECHAT_GATEWAY_STATE_DIR`
- last-contact binding under `WECHAT_GATEWAY_BINDING_STORE`

Required bridge env keys:

```bash
WECHAT_BRIDGE_DRIVER=gewechat
WECHAT_BRIDGE_NAME=gewechat
WECHAT_BRIDGE_API_BASE=http://gewechat-bridge:2531/v2/api
WECHAT_BRIDGE_APP_ID=your-app-id
WECHAT_BRIDGE_TOKEN=your-callback-token
WECHAT_BRIDGE_CALLBACK_URL=http://wechat-gateway:8080/bridges/gewechat/callback
```

Optional:

```bash
WECHAT_BRIDGE_AUTO_REGISTER_CALLBACK=true
WECHAT_GATEWAY_BINDING_STORE=/opt/hermes-persona/server-state/wechat-gateway/bindings.json
```

If enabled, `wechat-gateway` will attempt to register its callback URL with the
bridge on startup.

For a future cross-server `PadLocal + Wechaty` relay bridge, the equivalent env
shape is:

```bash
WECHAT_BRIDGE_DRIVER=padlocal-relay
WECHAT_BRIDGE_NAME=padlocal
WECHAT_BRIDGE_API_BASE=https://<domestic-bridge>/wechat-bridge/v1
WECHAT_BRIDGE_TOKEN=shared-relay-token
WECHAT_BRIDGE_CALLBACK_URL=https://<overseas-gateway-domain>/wechat/v1/messages/inbound
```

The relay bridge should post normalized inbound messages to the overseas
gateway using the existing gateway token:

```http
POST /wechat/v1/messages/inbound
X-Gateway-Token: <WECHAT_GATEWAY_TOKEN>
Content-Type: application/json
```

```json
{
  "conversation_id": "wechat:user_1",
  "user_id": "user_1",
  "text": "你好",
  "metadata": {
    "platform": "wechat",
    "bridge_name": "padlocal",
    "bridge_mode": "ipad",
    "to_wxid": "user_1",
    "ats": "",
    "updated_from": "padlocal_relay"
  }
}
```

For this single-node deployment, `gewechat-bridge` and `wechat-gateway` run on
the same Docker network, so the callback URL should point at the gateway's
internal service URL rather than a public domain.

Bridge source used by this repo:

- image: `registry.cn-chengdu.aliyuncs.com/tu1h/wechotd:alpine`
- API reference: Gewechat Apifox docs (`/tools/getTokenId`,
  `/login/getLoginQrCode`, `/login/checkLogin`, `/login/checkOnline`,
  `/tools/setCallback`, `/message/postText`)

Bridge login helper:

```bash
python3 scripts/gewechat_bridge.py get-token
python3 scripts/gewechat_bridge.py get-qr --token <token> --qr-file /tmp/gewechat-login.png
python3 scripts/gewechat_bridge.py check-login --token <token> --app-id <app_id> --uuid <uuid>
python3 scripts/gewechat_bridge.py set-callback --token <token> --app-id <app_id>
python3 scripts/gewechat_bridge.py check-online --token <token> --app-id <app_id>
```

## Proactive Outbound Path

Self-wake and future proactive messaging do not send directly to the bridge.
They reuse the existing `wechat-gateway` send path on the same server:

1. bridge inbound callback reaches `wechat-gateway`
2. `wechat-gateway` stores the latest bound target in `bindings.json`
3. Hermes self-wake calls `POST http://127.0.0.1:8081/wechat/v1/messages/outbound`
4. `wechat-gateway` sends via the same bridge client and chunking logic as normal replies

This preserves one outbound surface for:

- normal chat replies
- self-wake proactive messages
- later reminder-style pushes

## Hermes Host Env

Recommended values in `deploy/host/hermes-host.env`:

```bash
API_SERVER_ENABLED=true
API_SERVER_HOST=127.0.0.1
API_SERVER_PORT=8642
API_SERVER_KEY=change-me
API_SERVER_MODEL_NAME=caleb
HERMES_SELF_WAKE_ROLE_ID=caleb
HERMES_PROXY_PORT=11435
HERMES_HOME=/opt/hermes-persona/server-state/hermes
```

## Self-Wake Scheduler

The host now includes a minimal systemd-driven self-wake scheduler:

- `hermes-self-wake@<user>.service`
- `hermes-self-wake@<user>.timer`

It runs on the host, not in Docker, and executes:

```bash
/opt/hermes-persona/runtime/hermes-agent/venv/bin/python /opt/hermes-persona/scripts/run_self_wake.py
```

Current timer shape:

- `OnBootSec=8min`
- `OnUnitActiveSec=17min`
- `RandomizedDelaySec=11min`

That means self-wake checks do not land on fixed clock boundaries. The actual
go/no-go decision is still profile-scoped and enforced by:

- `self_wake_enabled`
- `wake_window_start` / `wake_window_end`
- `self_wake_min_gap_minutes`
- `proactive_cooldown_minutes`
- `max_daily_proactive_messages`
- recent real user interaction state

Useful commands:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now hermes-self-wake@$USER.timer
systemctl status hermes-self-wake@$USER.timer
systemctl list-timers | grep hermes-self-wake
python3 /opt/hermes-persona/scripts/run_self_wake.py --role caleb
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
