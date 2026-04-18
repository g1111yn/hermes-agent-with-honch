from __future__ import annotations

import json
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

    def send_message(self, *, conversation_id: str, text: str, metadata: dict[str, Any] | None = None) -> str:
        payload = {
            "model": self.config.model_name,
            "input": text,
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
