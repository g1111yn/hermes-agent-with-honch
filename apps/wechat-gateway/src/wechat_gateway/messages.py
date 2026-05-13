from __future__ import annotations

import math
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class OutboundMessage:
    type: str
    content: str


_MAX_SEGMENTS = 5

# Split right after sentence-ending punctuation (Chinese has no space after 。).
# Keeps the punctuation attached to the preceding clause.
_SENT_END_RE = re.compile(r"(?<=[。！？!?…])\s*")

# A line containing at least this many sentence-ending punctuation marks
# is treated as multiple sentences and will be expanded.
_MULTI_SENT_RE = re.compile(r"[。！？!?…]")


def segment_messages(text: str) -> list[OutboundMessage]:
    raw_lines = [l.strip() for l in str(text or "").splitlines() if l.strip()]
    if not raw_lines:
        return []

    # Pass 1: expand lines that contain 2+ sentence-ending punctuation marks
    # into individual sentences, regardless of line length.
    expanded: list[str] = []
    for line in raw_lines:
        if len(_MULTI_SENT_RE.findall(line)) >= 2:
            parts = [p.strip() for p in _SENT_END_RE.split(line) if p.strip()]
            if len(parts) > 1:
                expanded.extend(parts)
                continue
        expanded.append(line)

    if not expanded:
        return []

    # Pass 2: if within the limit, return as-is.
    if len(expanded) <= _MAX_SEGMENTS:
        return [OutboundMessage(type="text", content=_flatten_line(s)) for s in expanded]

    # Pass 3: more than MAX_SEGMENTS — merge into exactly MAX_SEGMENTS groups
    # so no content is silently dropped.
    groups = _distribute(expanded, _MAX_SEGMENTS)
    return [
        OutboundMessage(type="text", content=_flatten_line(" ".join(g)))
        for g in groups
    ]


def _distribute(items: list[str], n: int) -> list[list[str]]:
    """Split items into n roughly equal groups, front-loading the larger ones."""
    size = math.ceil(len(items) / n)
    groups: list[list[str]] = []
    for i in range(0, len(items), size):
        chunk = items[i : i + size]
        if chunk:
            groups.append(chunk)
    return groups[:n]


def _flatten_line(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()
