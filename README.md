# Hermes Persona

> A framework for running lifelike, long-memory, WeChat-native role-play
> agents on a single overseas Linux host — built on
> [Hermes Agent](https://github.com/anthropics/claude-code) + [Honcho](https://honcho.dev)
> with a biomimetic memory layer of our own.

🇺🇸 English · [🇨🇳 中文](#中文版)

---

## English

### What this project is

Hermes Persona is the **framework** for a single-node deployment of a
persona-driven chat agent that:

- runs **on your own Linux server**, no multi-tenant SaaS involved,
- reaches users over **WeChat** through a pluggable bridge gateway,
- keeps a **long-lived user memory** via Honcho's dialectic layer,
- adds a **biomimetic memory-surfacing layer** so the agent does *not*
  sound like an AI reciting facts it "remembers".

This repo publishes the framework only. **Role bundles, user memories, and
runtime state are kept out of git** — see [`.gitignore`](.gitignore).
You author your own persona under `roles/<your-role>/` and import it; the
framework never ships someone else's character.

### Project structure

```
hermes-persona/
├── apps/
│   └── wechat-gateway/            # bridge-agnostic WeChat interface service
│       ├── src/wechat_gateway/    # FastAPI app, bridge drivers, relay
│       └── tests/
├── deploy/
│   ├── docker-compose.yml         # honcho-api, deriver, postgres, redis, caddy, gateway
│   ├── caddy/Caddyfile            # reverse proxy
│   ├── systemd/                   # host-side unit templates (agent, proxy, self-wake)
│   ├── host/                      # host env template
│   └── *.env.*.example            # env templates (real .env files are git-ignored)
├── roles/
│   ├── README.md                  # how to author a role bundle
│   └── _template/                 # skeleton for new bundles
│       ├── SOUL.md
│       ├── memories/{MEMORY,USER}.md
│       └── presence-config.json
├── vendor/
│   └── hermes-agent/              # pinned upstream + patch bundle + overlay
│       ├── UPSTREAM.lock
│       ├── patches/
│       └── overlay/               # extra modules (e.g. presence)
├── scripts/
│   ├── bootstrap_hermes_vendor.sh # materialize the customized Hermes tree on a host
│   ├── import_role_bundle.sh      # copy a role bundle into the runtime profile dir
│   ├── install_server.sh          # env templates + systemd scaffolding
│   ├── hermes_model_proxy.py      # in-process model proxy (used by Honcho deriver)
│   ├── run_self_wake.py           # timer-driven proactive wake loop
│   └── verify_server_stack.py     # stack health check
├── docs/                          # deployment / architecture notes
├── legacy/                        # archived local PoC (reference only)
├── Makefile                       # host-runtime / server-install / stack-up / stack-ps
└── README.md
```

Everything under `server-state/`, `runtime/`, `data/`, and any concrete
`roles/<role-id>/` directory is host-local and excluded from git.

### Tech stack

| Layer              | Choice                                | Why this choice                                                                 |
|--------------------|---------------------------------------|---------------------------------------------------------------------------------|
| Agent runtime      | Hermes Agent (patched)                | First-class tool-use, streaming, provider-pluggable (Anthropic, OpenAI, custom).|
| Memory backend     | Honcho + pgvector                     | Dialectic layer already models user representation and peer cards out of the box.|
| Biomimetic overlay | Custom memory-manager middleware      | Adds surfacing restraint and absolute-time resolution without forking Honcho.   |
| Interface          | WeChat via bridge gateway (FastAPI)   | Reaches Chinese end-users directly; bridge is pluggable (gewechat / PadLocal).  |
| Model proxy        | Local Python proxy                    | Lets the Honcho deriver reuse the same provider credentials as the host Hermes. |
| Orchestration      | systemd (host) + Docker Compose       | Host agent keeps OAuth state persistent; containers handle stateful services.   |
| Reverse proxy      | Caddy                                 | Automatic TLS for the webhook endpoints.                                        |
| Datastore          | Postgres + Redis                      | Honcho's canonical pair; Redis handles the deriver queue.                       |

#### Why this split (host services + Docker stack)

Anthropic OAuth, model proxies, and long-running agents want a **stable host
identity**: file-backed token caches, systemd restarts, predictable ports.
Stateful services (Postgres, Redis, Honcho, WeChat bridge) want isolated
reproducibility. The semi-containerized layout gives you both — no OAuth
surprise on container restart, no host pollution from database upgrades.

### What we actually contribute on top of Hermes + Honcho

This is the substantive part. Everything else is plumbing.

1. **Biomimetic memory-surfacing layer.**
   Out of the box, Honcho + a long system prompt produces an agent that
   recites everything it remembers ("I remember you said you were
   tired yesterday…"). We added four coordinated restraints:
   - A `记忆浮现规则` section in `SOUL.md` banning retrieval-flavored phrases
     and capping memory repetition to one fact per 5 turns.
   - A tightened `honcho_conclude` tool description that only stores facts
     that will "still matter weeks from now" — no casual remarks, no moods.
   - A restraint clause added to the dialectic system prompt so
     `topic_suggestions` and `initiative_hint` default to "let the user lead"
     instead of resurfacing old memories.
   - A fenced `<memory-context>` injection block that tells the model to
     treat recalled memory as silent background, never as discussion
     material, and never to announce the recall.
2. **Absolute-time resolution before memory write.**
   Relative words like "明天 / tomorrow / next Friday" are resolved to a
   concrete `YYYY-MM-DD` date (using the system-prompt timestamp) before
   they enter Honcho. Without this, memories rot the moment time passes.
3. **Pluggable WeChat bridge gateway.**
   `apps/wechat-gateway` normalizes inbound/outbound messages, so the same
   persona runtime works against `gewechat` locally and a remote
   `PadLocal + Wechaty` relay — no agent-side coupling to any specific
   bridge protocol.
4. **Proactive self-wake loop.**
   `scripts/run_self_wake.py` under a systemd timer gives the agent the
   ability to initiate outbound messages through the same gateway surface
   it uses for replies — not a separate push path.
5. **Reproducible Hermes build.**
   `vendor/hermes-agent/` ships a pinned upstream commit + a binary-safe
   patch bundle + overlay files, materialized on the host by
   `bootstrap_hermes_vendor.sh`. This keeps the repo lightweight while
   making the Hermes customization fully reproducible.

### Quick start (Linux host)

> Requires: Debian/Ubuntu 22.04+, Docker Engine + compose plugin, Python 3.11+,
> a DNS name pointing at the host, and the ability to open 443 + the bridge port.

```bash
# 1. Clone onto the host
sudo mkdir -p /opt/hermes-persona && sudo chown $USER:$USER /opt/hermes-persona
git clone https://github.com/<you>/hermes-persona.git /opt/hermes-persona
cd /opt/hermes-persona

# 2. Materialize the customized Hermes runtime on the host
make host-runtime                  # runs scripts/setup_host_runtime.sh

# 3. Install env templates + systemd unit files
make server-install                # runs scripts/install_server.sh

# 4. Fill in secrets and domain names
$EDITOR deploy/.env.shared         # copied from .env.shared.example
$EDITOR deploy/.env.honcho
$EDITOR deploy/.env.interface
$EDITOR deploy/.env.providers
$EDITOR deploy/host/hermes-host.env

# 5. Author or import a role bundle
cp -r roles/_template roles/my-role
$EDITOR roles/my-role/SOUL.md
$EDITOR roles/my-role/memories/MEMORY.md
$EDITOR roles/my-role/presence-config.json
./scripts/import_role_bundle.sh my-role   # copies into server-state/hermes/profiles/

# 6. Start host services
sudo systemctl daemon-reload
sudo systemctl enable --now hermes-agent@$USER.service hermes-model-proxy@$USER.service

# 7. Start the container stack
make stack-up                      # docker compose up -d

# 8. Verify
make stack-ps
python3 ./scripts/verify_server_stack.py
```

Once the stack is healthy:

- Caddy terminates TLS on your domain and routes `/wechat/v1/*` to the
  gateway and `/honcho/*` to the Honcho API.
- The WeChat bridge logs in (scan QR if using `gewechat`), then delivers
  inbound messages to the gateway → host Hermes → Honcho.
- Self-wake timer fires per your configured schedule and pushes outbound
  messages through the same gateway.

### How to author a role

1. Copy the skeleton:
   ```bash
   cp -r roles/_template roles/<role-id>
   ```
2. Edit `SOUL.md` — this is the core persona (identity, voice,
   reply-shape rules, hard constraints, few-shot examples).
3. Edit `memories/MEMORY.md` — role-scoped ground-truth facts.
   Leave `memories/USER.md` empty; the memory system fills it over time.
4. Edit `presence-config.json` — initiative style, interest topics,
   proactive attention knobs for the self-wake loop.
5. (Optional) Add `skills/<name>/SKILL.md` files for mode-specific behavior
   cards that the agent can consult when the conversation shifts mode.
6. Import:
   ```bash
   ./scripts/import_role_bundle.sh <role-id>
   sudo systemctl restart hermes-agent@$USER.service
   ```

The `server-state/hermes/profiles/<role-id>/` tree is the **active runtime
copy**. It is host-local, git-ignored, and rewritten each time you import.

### Memory system cheat-sheet

- **What gets stored:** explicit user corrections, stable preferences,
  significant personal facts, time-anchored plans (with absolute dates).
- **What does NOT get stored:** casual moods, one-off complaints, small
  talk, anything only relevant to today.
- **How to call memory tools:** the agent has `honcho_profile`,
  `honcho_search`, `honcho_context`, `honcho_conclude` available; the
  framework's system prompt already constrains *when* to call them.
- **How to surface memory in replies:** don't. Recalled context is
  injected as a fenced `<memory-context>` block and the system note tells
  the model to treat it as silent background. Memories only show up in
  replies when the user's current message connects to them naturally.

### Troubleshooting

```bash
# Host agent logs
journalctl -u hermes-agent@$USER.service -f

# Stack health
make stack-ps
python3 ./scripts/verify_server_stack.py

# Regenerate the Hermes patch after local edits
./scripts/refresh_hermes_patch.sh
```

### License & scope

The framework code under `apps/`, `deploy/`, `scripts/`, `vendor/*/patches`,
and `vendor/*/overlay` is the part intended for redistribution. Persona
content, user memories, and runtime state are the operator's own and are
excluded by `.gitignore` by design.

---

## 中文版

### 这个项目是什么

Hermes Persona 是一个**框架**，用来在单台海外 Linux
服务器上跑一个"像真人""有长期记忆""直接在微信里说话"的角色扮演
智能体。底层基于
[Hermes Agent](https://github.com/anthropics/claude-code) + [Honcho](https://honcho.dev)，
在上面加了一层我们自己的**仿生记忆浮现机制**。

这个仓库只发布**框架**。**角色文件、用户记忆、运行时状态全部被 `.gitignore`
挡住**。你在自己机器上的 `roles/<role-id>/` 下写自己的角色，再用脚本导入。
框架本身不带任何别人的人设。

### 项目结构

```
hermes-persona/
├── apps/
│   └── wechat-gateway/            # 与 bridge 解耦的微信接入服务
│       ├── src/wechat_gateway/    # FastAPI 应用、bridge 驱动、relay
│       └── tests/
├── deploy/
│   ├── docker-compose.yml         # honcho-api、deriver、postgres、redis、caddy、gateway
│   ├── caddy/Caddyfile            # 反向代理
│   ├── systemd/                   # 宿主机 unit 模板（agent、proxy、self-wake）
│   ├── host/                      # 宿主机 env 模板
│   └── *.env.*.example            # 环境变量模板（真实 .env 不入库）
├── roles/
│   ├── README.md                  # 如何写一个角色 bundle
│   └── _template/                 # 新角色骨架
│       ├── SOUL.md
│       ├── memories/{MEMORY,USER}.md
│       └── presence-config.json
├── vendor/
│   └── hermes-agent/              # 锁定的上游 + 补丁包 + overlay
│       ├── UPSTREAM.lock
│       ├── patches/
│       └── overlay/               # 额外模块（比如 presence）
├── scripts/
│   ├── bootstrap_hermes_vendor.sh # 在宿主机展开定制版 Hermes
│   ├── import_role_bundle.sh      # 把角色 bundle 拷进运行时 profile
│   ├── install_server.sh          # 生成 env 模板 + systemd 脚手架
│   ├── hermes_model_proxy.py      # 进程内模型代理（给 Honcho deriver 用）
│   ├── run_self_wake.py           # 定时主动唤醒脚本
│   └── verify_server_stack.py     # 整栈健康检查
├── docs/                          # 部署与架构笔记
├── legacy/                        # 本地 PoC 归档，仅作参考
├── Makefile                       # host-runtime / server-install / stack-up / stack-ps
└── README.md
```

`server-state/`、`runtime/`、`data/`、具体的 `roles/<role-id>/` 目录都是
宿主机本地数据，不会进 git。

### 技术栈

| 层次           | 选型                                   | 为什么是它                                                             |
|----------------|----------------------------------------|------------------------------------------------------------------------|
| Agent 运行时   | Hermes Agent（打补丁版）               | 原生 tool-use、流式输出、Provider 可插拔（Anthropic、OpenAI、自定义）。|
| 记忆后端       | Honcho + pgvector                      | 自带 dialectic 层，开箱就能建用户画像和 peer card。                    |
| 仿生层         | 自研 memory-manager 中间件             | 不 fork Honcho，在外层加浮现克制与相对时间换算。                       |
| 接入层         | 微信 bridge 网关（FastAPI）            | 直连国内用户；bridge 可换（gewechat / PadLocal）。                     |
| 模型代理       | 本地 Python proxy                      | Honcho deriver 复用宿主机 Hermes 的 provider 凭证。                    |
| 编排           | systemd（宿主） + Docker Compose       | Agent 和 OAuth 留在宿主机，状态服务容器化。                            |
| 反代           | Caddy                                  | Webhook 自动 TLS。                                                     |
| 数据           | Postgres + Redis                       | Honcho 标配；Redis 做 deriver 队列。                                   |

#### 为什么这么分（宿主服务 + 容器栈）

Anthropic OAuth、模型代理、长跑的 agent 需要**稳定的宿主身份**：文件态的
token、systemd 自动拉起、端口固定。状态服务（Postgres、Redis、Honcho、
微信 bridge）要隔离、要可重建。半容器化把这两个需求分开：容器重启不会把
OAuth 搞丢，数据库升级也不会污染宿主。

### 我们在 Hermes + Honcho 上到底做了什么

这是真正有重量的部分，其它都是管道。

1. **仿生记忆浮现机制。**
   默认配置下，Honcho + 长 system prompt 会训出一个"把记得的东西全背出来"
   的 agent（"我记得你昨天说你很累……"）。我们加了四重协调约束：
   - 在 `SOUL.md` 里加了 `记忆浮现规则` 章节，明令禁止"我记得你说过"
     这类召回式句式，并把同一事实的重复频率压到 5 轮 1 次。
   - 把 `honcho_conclude` 工具描述收紧到"几周后还重要的事才存"，过滤掉
     临时情绪、随口抱怨。
   - 在 dialectic system prompt 里加了克制条款，让
     `topic_suggestions` 和 `initiative_hint` 默认"让用户主导"，而不是
     主动翻旧账。
   - `<memory-context>` 注入块带一条系统说明：把召回记忆当沉默背景，
     不要在回复里主动提起，也不要说"我记得"。
2. **写入记忆前先把相对时间换成绝对日期。**
   "明天/下周/周五"这类词，写进 Honcho 前先用 system prompt 里的
   `Conversation started` 日期换算成 `YYYY-MM-DD`。不换算的话，过几天这
   条记忆就失去锚点了。
3. **可插拔的微信 bridge 网关。**
   `apps/wechat-gateway` 做了入站/出站消息归一化，所以同一个人设运行时
   既能接本地的 `gewechat`，也能接远程的 `PadLocal + Wechaty` relay ——
   agent 侧不跟任何 bridge 协议耦合。
4. **主动唤醒循环。**
   `scripts/run_self_wake.py` 挂在 systemd timer 下，让 agent 能主动发
   消息，而且走的是跟回消息同一条 gateway 通道，不是另开一条推送路径。
5. **可重建的 Hermes 定制版。**
   `vendor/hermes-agent/` 里只有固定上游 commit + 二进制安全的 patch 包
   + overlay 文件，真正的 Hermes 树由 `bootstrap_hermes_vendor.sh` 在
   宿主机展开。仓库本身体积很小，但定制版是完全可重现的。

### 快速开始（Linux 服务器）

> 前置：Debian/Ubuntu 22.04+、Docker Engine + compose 插件、Python 3.11+，
> 一条指向本机的域名，以及 443 和 bridge 端口的开放能力。

```bash
# 1. 把仓库克隆到宿主机
sudo mkdir -p /opt/hermes-persona && sudo chown $USER:$USER /opt/hermes-persona
git clone https://github.com/<you>/hermes-persona.git /opt/hermes-persona
cd /opt/hermes-persona

# 2. 在宿主机展开定制版 Hermes
make host-runtime                  # scripts/setup_host_runtime.sh

# 3. 生成 env 模板 + systemd 脚手架
make server-install                # scripts/install_server.sh

# 4. 填密钥、域名
$EDITOR deploy/.env.shared         # 从 .env.shared.example 拷过来
$EDITOR deploy/.env.honcho
$EDITOR deploy/.env.interface
$EDITOR deploy/.env.providers
$EDITOR deploy/host/hermes-host.env

# 5. 写 / 导入角色 bundle
cp -r roles/_template roles/my-role
$EDITOR roles/my-role/SOUL.md
$EDITOR roles/my-role/memories/MEMORY.md
$EDITOR roles/my-role/presence-config.json
./scripts/import_role_bundle.sh my-role   # 拷进 server-state/hermes/profiles/

# 6. 启动宿主服务
sudo systemctl daemon-reload
sudo systemctl enable --now hermes-agent@$USER.service hermes-model-proxy@$USER.service

# 7. 启动容器栈
make stack-up                      # docker compose up -d

# 8. 验证
make stack-ps
python3 ./scripts/verify_server_stack.py
```

整栈起来之后：

- Caddy 接管域名 TLS，把 `/wechat/v1/*` 路由到 gateway，`/honcho/*` 路由到
  Honcho API。
- 微信 bridge 登录（`gewechat` 走扫码），入站消息经 gateway → 宿主 Hermes
  → Honcho。
- Self-wake timer 按配置触发，走同一条 gateway 通道主动发消息。

### 怎么写一个角色

1. 拷骨架：
   ```bash
   cp -r roles/_template roles/<role-id>
   ```
2. 写 `SOUL.md` —— 核心人设（身份、语气、回复形态硬规则、硬约束、few-shot
   示例）。
3. 写 `memories/MEMORY.md` —— 角色侧的事实锚点。
   `memories/USER.md` 留空，记忆系统会自己填。
4. 写 `presence-config.json` —— 主动性风格、兴趣话题、self-wake 的关注档位。
5.（可选）在 `skills/<name>/SKILL.md` 下放模式卡，让 agent 在不同场景切换
   行为档位。
6. 导入：
   ```bash
   ./scripts/import_role_bundle.sh <role-id>
   sudo systemctl restart hermes-agent@$USER.service
   ```

`server-state/hermes/profiles/<role-id>/` 是**运行时副本**，是宿主本地、
git 忽略，每次 import 都会整覆盖。

### 记忆系统速查

- **会存：** 用户明确的纠正、稳定的偏好、重要的个人事实、带绝对日期的计划。
- **不会存：** 临时情绪、一次性抱怨、闲聊、只跟今天相关的事。
- **工具：** agent 有 `honcho_profile`、`honcho_search`、`honcho_context`、
  `honcho_conclude` 四个工具，框架的 system prompt 已经约束了**什么时候**调。
- **怎么在回复里用记忆：** 不要主动用。召回上下文会被包在
  `<memory-context>` 围栏里注入，system note 告诉模型把它当沉默背景。
  只有当用户当前消息自然接上了旧记忆时，才顺势接住，不要说"我记得"。

### 常见排查

```bash
# 宿主 agent 日志
journalctl -u hermes-agent@$USER.service -f

# 整栈健康
make stack-ps
python3 ./scripts/verify_server_stack.py

# 本地改完 Hermes 后重新生成 patch
./scripts/refresh_hermes_patch.sh
```

### 许可与边界

`apps/`、`deploy/`、`scripts/`、`vendor/*/patches`、`vendor/*/overlay`
是框架代码，可以转发。角色内容、用户记忆、运行时状态是运营者本人的资产，
`.gitignore` 默认已经把它们挡住。
