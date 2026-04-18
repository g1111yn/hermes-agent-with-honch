from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import datetime as dt
import json


@dataclass(slots=True)
class TurnRecord:
    role: str
    content: str
    timestamp: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class TranscriptRecord:
    user_id: str
    session_id: str
    created_at: str
    updated_at: str
    turns: list[TurnRecord]


class TranscriptStore:
    def __init__(self, root: Path, user_id: str) -> None:
        self.root = root / user_id / "transcripts"
        self.root.mkdir(parents=True, exist_ok=True)
        self.user_id = user_id

    def _json_path(self, session_id: str) -> Path:
        return self.root / f"{session_id}.json"

    def _markdown_path(self, session_id: str) -> Path:
        return self.root / f"{session_id}.md"

    def load(self, session_id: str) -> TranscriptRecord:
        path = self._json_path(session_id)
        if not path.exists():
            now = _utc_now()
            record = TranscriptRecord(
                user_id=self.user_id,
                session_id=session_id,
                created_at=now,
                updated_at=now,
                turns=[],
            )
            self._save(record)
            return record
        payload = json.loads(path.read_text(encoding="utf-8"))
        return TranscriptRecord(
            user_id=payload["user_id"],
            session_id=payload["session_id"],
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
            turns=[TurnRecord(**item) for item in payload["turns"]],
        )

    def append(self, session_id: str, role: str, content: str, metadata: dict[str, object] | None = None) -> TranscriptRecord:
        record = self.load(session_id)
        record.turns.append(
            TurnRecord(
                role=role,
                content=content.strip(),
                timestamp=_utc_now(),
                metadata=metadata or {},
            )
        )
        record.updated_at = _utc_now()
        self._save(record)
        return record

    def recent_turns(self, session_id: str, limit: int) -> list[TurnRecord]:
        record = self.load(session_id)
        return record.turns[-limit:]

    def export_paths(self, session_id: str) -> tuple[Path, Path]:
        return self._json_path(session_id), self._markdown_path(session_id)

    def _save(self, record: TranscriptRecord) -> None:
        payload = {
            "user_id": record.user_id,
            "session_id": record.session_id,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "turns": [
                {
                    "role": turn.role,
                    "content": turn.content,
                    "timestamp": turn.timestamp,
                    "metadata": turn.metadata,
                }
                for turn in record.turns
            ],
        }
        self._json_path(record.session_id).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self._markdown_path(record.session_id).write_text(
            self._to_markdown(record),
            encoding="utf-8",
        )

    def _to_markdown(self, record: TranscriptRecord) -> str:
        lines = [
            f"# Transcript: {record.session_id}",
            "",
            f"- User: `{record.user_id}`",
            f"- Created: `{record.created_at}`",
            f"- Updated: `{record.updated_at}`",
            "",
        ]
        for turn in record.turns:
            lines.extend(
                [
                    f"## {turn.role} @ {turn.timestamp}",
                    "",
                    turn.content,
                    "",
                ]
            )
        return "\n".join(lines).rstrip() + "\n"


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()
