from __future__ import annotations

import json
import time
from pathlib import Path


class DedupeStore:
    def __init__(self, path: Path, ttl_seconds: int = 300):
        self.path = path
        self.ttl_seconds = ttl_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def seen(self, key: str) -> bool:
        now = int(time.time())
        data = self._load(now)
        if key in data:
            self._save(data)
            return True
        data[key] = now
        self._save(data)
        return False

    def _load(self, now: int) -> dict[str, int]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        pruned: dict[str, int] = {}
        for key, ts in payload.items():
            if not isinstance(ts, int):
                continue
            if now - ts <= self.ttl_seconds:
                pruned[key] = ts
        return pruned

    def _save(self, data: dict[str, int]) -> None:
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
