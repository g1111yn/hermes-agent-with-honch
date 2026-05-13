from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RelayBridgeClientConfig:
    api_base: str
    app_id: str
    token: str
    callback_url: str
    auto_register_callback: bool


class RelayBridgeClient:
    """Generic HTTP relay for a custom bridge service.

    Expected remote endpoints:
    - POST {api_base}/messages/send
    - POST {api_base}/callbacks/register
    """

    def __init__(self, config: RelayBridgeClientConfig):
        self.config = config

    def register_callback(self) -> dict[str, Any]:
        return self._post(
            "/callbacks/register",
            {
                "callback_url": self.config.callback_url,
                "app_id": self.config.app_id,
            },
        )

    def download_image(self, *, msg_id: str, app_id: str | None = None) -> bytes | None:
        return None

    def send_text(self, *, to_wxid: str, content: str, ats: str = "") -> dict[str, Any]:
        return self._post(
            "/messages/send",
            {
                "app_id": self.config.app_id,
                "to_wxid": to_wxid,
                "content": content,
                "ats": ats,
            },
        )

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.config.token:
            headers["X-Bridge-Token"] = self.config.token
        request = urllib.request.Request(
            f"{self.config.api_base}{path}",
            data=data,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
