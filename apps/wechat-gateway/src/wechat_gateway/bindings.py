from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class BindingStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def save_last_target(self, *, model_name: str, target: dict[str, Any]) -> None:
        payload = self.load()
        payload[str(model_name).strip() or "default"] = target
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def get_last_target(self, model_name: str) -> dict[str, Any] | None:
        payload = self.load()
        target = payload.get(str(model_name).strip() or "default")
        return target if isinstance(target, dict) else None
