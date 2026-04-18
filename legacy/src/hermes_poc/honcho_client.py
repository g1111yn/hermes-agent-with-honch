from __future__ import annotations

from dataclasses import dataclass
import http.client
import json
from pathlib import Path
from typing import Any
from urllib import error, parse


@dataclass(slots=True)
class HonchoSignals:
    source: str
    need_state: str
    emotional_tone: str
    initiative_hint: str
    topic_suggestions: list[str]
    reasoning: str
    confidence: float
    raw: dict[str, Any]

    @classmethod
    def fallback(cls, reason: str) -> "HonchoSignals":
        return cls(
            source="fallback",
            need_state="steady",
            emotional_tone="neutral",
            initiative_hint="",
            topic_suggestions=[],
            reasoning=reason,
            confidence=0.0,
            raw={"error": reason},
        )


class HonchoClient:
    def __init__(self, base_url: str, timeout_seconds: int, enabled: bool) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.enabled = enabled

    def get_state(self, payload: dict[str, Any]) -> HonchoSignals:
        if not self.enabled:
            return HonchoSignals.fallback("Honcho disabled in runtime config.")
        try:
            parsed_url = parse.urlparse(f"{self.base_url}/signals")
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            connection_cls = http.client.HTTPSConnection if parsed_url.scheme == "https" else http.client.HTTPConnection
            connection = connection_cls(parsed_url.hostname, parsed_url.port, timeout=self.timeout_seconds)
            connection.request(
                "POST",
                parsed_url.path or "/signals",
                body=body,
                headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
            )
            response = connection.getresponse()
            parsed = json.loads(response.read().decode("utf-8"))
            connection.close()
            return HonchoSignals(
                source="honcho-service",
                need_state=parsed.get("need_state", "steady"),
                emotional_tone=parsed.get("emotional_tone", "neutral"),
                initiative_hint=parsed.get("initiative_hint", ""),
                topic_suggestions=list(parsed.get("topic_suggestions", [])),
                reasoning=parsed.get("reasoning", ""),
                confidence=float(parsed.get("confidence", 0.0)),
                raw=parsed,
            )
        except (error.URLError, TimeoutError, json.JSONDecodeError, http.client.HTTPException, OSError) as exc:
            return HonchoSignals.fallback(f"Honcho request failed: {exc}")

    @staticmethod
    def persist_latest(path: Path, signals: HonchoSignals) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "source": signals.source,
            "need_state": signals.need_state,
            "emotional_tone": signals.emotional_tone,
            "initiative_hint": signals.initiative_hint,
            "topic_suggestions": signals.topic_suggestions,
            "reasoning": signals.reasoning,
            "confidence": signals.confidence,
            "raw": signals.raw,
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
