from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class OutboundMessage:
    type: str
    content: str


def segment_messages(text: str) -> list[OutboundMessage]:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return []
    if len(lines) == 1:
        return [OutboundMessage(type="text", content=_flatten_line(lines[0]))]
    return [OutboundMessage(type="text", content=_flatten_line(line)) for line in lines[:3]]


def _flatten_line(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()
