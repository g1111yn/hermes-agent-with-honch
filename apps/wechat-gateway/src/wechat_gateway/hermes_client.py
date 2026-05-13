from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HermesClientConfig:
    base_url: str
    api_key: str
    model_name: str


class HermesClient:
    def __init__(self, config: HermesClientConfig):
        self.config = config

    def send_message(
        self,
        *,
        conversation_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
        image_bytes: bytes | None = None,
    ) -> str:
        if image_bytes:
            import base64 as _b64
            b64 = _b64.b64encode(image_bytes).decode("ascii")
            input_content: Any = [
                {"type": "input_text", "text": text or "[图片]"},
                {"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64}"},
            ]
        else:
            input_content = text
        payload = {
            "model": self.config.model_name,
            "input": input_content,
            "conversation": conversation_id,
            "store": True,
            "metadata": metadata or {},
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.config.base_url}/responses",
            data=data,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = json.loads(response.read().decode("utf-8"))
        return _extract_output_text(raw)

    def report_interaction(
        self,
        *,
        role_id: str,
        direction: str,
        text: str,
        conversation_id: str = "",
        platform: str = "wechat",
        metadata: dict[str, Any] | None = None,
        sent: bool = True,
        proactive: bool = False,
    ) -> bool:
        payload = {
            "direction": direction,
            "text": text,
            "conversation_id": conversation_id,
            "platform": platform,
            "metadata": metadata or {},
            "sent": sent,
            "proactive": proactive,
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.config.base_url}/roles/{role_id}/interaction",
            data=data,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
            return False
        return bool(isinstance(raw, dict) and raw.get("ok"))


def _extract_output_text(payload: dict[str, Any]) -> str:
    output = payload.get("output") or []
    parts: list[str] = []
    for item in output:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "output_text":
                text = str(content.get("text") or "").strip()
                if text:
                    parts.append(text)
    return "\n".join(parts).strip()
