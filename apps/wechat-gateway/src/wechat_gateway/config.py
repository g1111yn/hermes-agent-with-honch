from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GatewayConfig:
    host: str
    port: int
    gateway_token: str
    hermes_api_base: str
    hermes_api_key: str
    hermes_model_name: str
    bridge_mode: str
    bridge_name: str
    chunk_delay_seconds: float
    dedupe_store_path: str
    dedupe_ttl_seconds: int
    bridge_api_base: str
    bridge_app_id: str
    bridge_token: str
    bridge_callback_url: str
    bridge_auto_register_callback: bool

    @classmethod
    def from_env(cls) -> "GatewayConfig":
        state_dir = Path(os.getenv("WECHAT_GATEWAY_STATE_DIR", "./data/wechat-gateway")).expanduser()
        return cls(
            host=os.getenv("WECHAT_GATEWAY_HOST", "0.0.0.0"),
            port=int(os.getenv("WECHAT_GATEWAY_PORT", "8080")),
            gateway_token=os.getenv("WECHAT_GATEWAY_TOKEN", "").strip(),
            hermes_api_base=os.getenv("HERMES_API_BASE", "http://host.docker.internal:8642/v1").rstrip("/"),
            hermes_api_key=os.getenv("HERMES_API_KEY", "").strip(),
            hermes_model_name=os.getenv("HERMES_MODEL_NAME", "hermes-agent").strip() or "hermes-agent",
            bridge_mode=os.getenv("WECHAT_BRIDGE_MODE", "ipad").strip() or "ipad",
            bridge_name=os.getenv("WECHAT_BRIDGE_NAME", "placeholder").strip() or "placeholder",
            chunk_delay_seconds=float(os.getenv("WECHAT_CHUNK_DELAY_SECONDS", "0.9")),
            dedupe_store_path=os.getenv("WECHAT_GATEWAY_DEDUPE_STORE", str(state_dir / "dedupe.json")).strip(),
            dedupe_ttl_seconds=int(os.getenv("WECHAT_GATEWAY_DEDUPE_TTL_SECONDS", "300")),
            bridge_api_base=os.getenv("WECHAT_BRIDGE_API_BASE", "http://127.0.0.1:2531/v2/api").rstrip("/"),
            bridge_app_id=os.getenv("WECHAT_BRIDGE_APP_ID", "").strip(),
            bridge_token=os.getenv("WECHAT_BRIDGE_TOKEN", "").strip(),
            bridge_callback_url=os.getenv("WECHAT_BRIDGE_CALLBACK_URL", "").strip(),
            bridge_auto_register_callback=os.getenv("WECHAT_BRIDGE_AUTO_REGISTER_CALLBACK", "false").strip().lower() in {"1", "true", "yes", "on"},
        )
