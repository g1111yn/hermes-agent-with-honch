from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .gewechat import GewechatClient, GewechatClientConfig
from .relay import RelayBridgeClient, RelayBridgeClientConfig


@dataclass(frozen=True)
class BridgeClientConfig:
    driver: str
    api_base: str
    app_id: str
    token: str
    callback_url: str
    auto_register_callback: bool


class BridgeClient(Protocol):
    def register_callback(self) -> dict[str, Any]:
        ...

    def send_text(self, *, to_wxid: str, content: str, ats: str = "") -> dict[str, Any]:
        ...

    def download_image(self, *, msg_id: str, app_id: str | None = None) -> bytes | None:
        ...


def build_bridge_client(config: BridgeClientConfig) -> BridgeClient:
    driver = config.driver.strip().lower()
    if driver == "gewechat":
        return GewechatClient(
            GewechatClientConfig(
                api_base=config.api_base,
                app_id=config.app_id,
                token=config.token,
                callback_url=config.callback_url,
                auto_register_callback=config.auto_register_callback,
            )
        )
    if driver in {"relay", "http-relay", "padlocal-relay", "padlocal"}:
        return RelayBridgeClient(
            RelayBridgeClientConfig(
                api_base=config.api_base,
                app_id=config.app_id,
                token=config.token,
                callback_url=config.callback_url,
                auto_register_callback=config.auto_register_callback,
            )
        )
    raise ValueError(f"Unsupported bridge driver: {config.driver}")
