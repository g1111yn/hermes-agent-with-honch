from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import json
from pathlib import Path
import re

from hermes_poc.assets import CharacterBundle
from hermes_poc.honcho_client import HonchoSignals
from hermes_poc.transcript import TurnRecord


@dataclass(slots=True)
class MemoryState:
    profile_facts: list[str]
    relationship_state: str
    important_events: list[str]
    open_threads: list[str]
    style_anchors: list[str]
    last_session_summary: str
    updated_at: str


class MemoryStore:
    def __init__(self, data_dir: Path, character: CharacterBundle, user_id: str) -> None:
        self.root = data_dir / "users" / user_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.memory_json_path = self.root / "memory.json"
        self.memory_markdown_path = self.root / "MEMORY.md"
        self.summary_dir = self.root / "summaries"
        self.summary_dir.mkdir(parents=True, exist_ok=True)
        self.character = character

    def load(self) -> MemoryState:
        if not self.memory_json_path.exists():
            state = self._bootstrap()
            self.save(state)
            return state
        payload = json.loads(self.memory_json_path.read_text(encoding="utf-8"))
        return MemoryState(
            profile_facts=list(payload["profile_facts"]),
            relationship_state=payload["relationship_state"],
            important_events=list(payload["important_events"]),
            open_threads=list(payload["open_threads"]),
            style_anchors=list(payload["style_anchors"]),
            last_session_summary=payload["last_session_summary"],
            updated_at=payload["updated_at"],
        )

    def save(self, state: MemoryState) -> None:
        payload = {
            "profile_facts": state.profile_facts,
            "relationship_state": state.relationship_state,
            "important_events": state.important_events,
            "open_threads": state.open_threads,
            "style_anchors": state.style_anchors,
            "last_session_summary": state.last_session_summary,
            "updated_at": state.updated_at,
        }
        self.memory_json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        self.memory_markdown_path.write_text(self.render_markdown(state), encoding="utf-8")

    def recent_summaries(self, limit: int = 3) -> list[str]:
        paths = sorted(self.summary_dir.glob("*.md"))
        return [path.read_text(encoding="utf-8") for path in paths[-limit:]]

    def write_session_summary(self, session_id: str, turns: list[TurnRecord]) -> Path:
        user_lines = [turn.content for turn in turns if turn.role == "user"][-4:]
        assistant_lines = [turn.content for turn in turns if turn.role == "assistant"][-4:]
        lines = [
            f"# Session Summary: {session_id}",
            "",
            "## Key User Beats",
            "",
        ]
        lines.extend([f"- {line}" for line in user_lines] or ["- No user turns recorded."])
        lines.extend(["", "## Character Beats", ""])
        lines.extend([f"- {line}" for line in assistant_lines] or ["- No assistant turns recorded."])
        path = self.summary_dir / f"{session_id}.md"
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return path

    def maybe_update(
        self,
        *,
        threshold: int,
        user_text: str,
        assistant_text: str,
        honcho: HonchoSignals,
    ) -> tuple[MemoryState, bool, list[str]]:
        state = self.load()
        score, notes = self._score(user_text)
        changes: list[str] = []
        self._extract_profile_facts(state, user_text, changes)
        self._extract_threads(state.open_threads, user_text, changes)
        self._extract_events(state.important_events, user_text, changes)
        self._update_relationship_state(state, user_text, honcho, changes)
        if assistant_text and "下次" in assistant_text:
            _append_unique(state.open_threads, "Assistant suggested a future follow-up.")
        should_write = score >= threshold or bool(changes)
        if should_write:
            state.profile_facts = _dedupe(state.profile_facts)
            state.important_events = _dedupe(state.important_events)[-12:]
            state.open_threads = _dedupe(state.open_threads)[-10:]
            state.style_anchors = _dedupe(state.style_anchors)
            state.updated_at = _utc_now()
            state.last_session_summary = notes[0] if notes else state.last_session_summary
            self.save(state)
        return state, should_write, changes

    def render_markdown(self, state: MemoryState) -> str:
        def bullets(items: list[str], empty: str) -> list[str]:
            return [f"- {item}" for item in items] if items else [f"- {empty}"]

        lines = [
            "# Long-Term Memory",
            "",
            f"- Updated: `{state.updated_at}`",
            "",
            "## Profile Facts",
            "",
            *bullets(state.profile_facts, "No durable profile facts yet."),
            "",
            "## Relationship State",
            "",
            f"- {state.relationship_state}",
            "",
            "## Important Events",
            "",
            *bullets(state.important_events, "No major events stored yet."),
            "",
            "## Open Threads",
            "",
            *bullets(state.open_threads, "No open threads."),
            "",
            "## Style Anchors",
            "",
            *bullets(state.style_anchors, "No style anchors."),
            "",
            "## Last Session Summary",
            "",
            f"- {state.last_session_summary or 'No summary yet.'}",
            "",
        ]
        return "\n".join(lines)

    def _bootstrap(self) -> MemoryState:
        user_sections = self.character.user_sections
        memory_sections = self.character.memory_sections
        return MemoryState(
            profile_facts=_dedupe(user_sections.get("stable-facts", []) + memory_sections.get("profile-facts", [])),
            relationship_state=(memory_sections.get("relationship-state", ["Early-stage relationship; warm but measured."]) or ["Early-stage relationship; warm but measured."])[0],
            important_events=memory_sections.get("important-events", []),
            open_threads=memory_sections.get("open-threads", []),
            style_anchors=_dedupe(user_sections.get("style-anchors", []) + memory_sections.get("style-anchors", [])),
            last_session_summary="Initial memory seed loaded.",
            updated_at=_utc_now(),
        )

    def _score(self, user_text: str) -> tuple[int, list[str]]:
        score = 0
        notes: list[str] = []
        lowered = user_text.lower()
        patterns = {
            "remember": ["记住", "remember", "下次", "改成"],
            "identity": ["我叫", "call me", "我是", "my name is", "from now on"],
            "emotion": ["难过", "开心", "焦虑", "累", "紧张", "生气"],
            "preference": ["喜欢", "讨厌", "prefer", "不喜欢", "i like", "i do not like", "i don't like"],
        }
        for label, keywords in patterns.items():
            if any(keyword in user_text or keyword in lowered for keyword in keywords):
                score += 1
                notes.append(f"Captured {label} signal from the latest turn.")
        return score, notes or ["Routine turn with no durable memory signal."]

    def _extract_profile_facts(self, state: MemoryState, user_text: str, changes: list[str]) -> None:
        facts = state.profile_facts
        patterns = [
            (r"我叫([^\s，。!！?？]{1,12})", "User says their name is {match}."),
            (r"叫我([^\s，。!！?？]{1,12})", "User prefers to be called {match}."),
            (r"我喜欢([^，。!！?？]{1,20})", "User likes {match}."),
            (r"我不喜欢([^，。!！?？]{1,20})", "User dislikes {match}."),
            (r"我是([^，。!！?？]{1,20})", "User identifies as {match}."),
            (r"我在([^，。!！?？]{1,20})", "User is currently in {match}."),
            (r"(?i)call me ([a-z0-9 _-]{1,24})", "User prefers to be called {match}."),
            (r"(?i)my name is ([a-z0-9 _-]{1,24})", "User says their name is {match}."),
            (r"(?i)i like ([^,.!?]{1,40})", "User likes {match}."),
            (r"(?i)i do not like ([^,.!?]{1,40})", "User dislikes {match}."),
            (r"(?i)i don't like ([^,.!?]{1,40})", "User dislikes {match}."),
            (r"(?i)i am ([^,.!?]{1,40})", "User identifies as {match}."),
        ]
        for pattern, template in patterns:
            match = re.search(pattern, user_text)
            if not match:
                continue
            captured = match.group(1).strip()
            if template == "User identifies as {match}." and captured.lower() in {"back", "here", "okay", "fine"}:
                continue
            fact = template.format(match=captured)
            if _append_unique(facts, fact):
                changes.append(fact)
            if fact.startswith("User prefers to be called "):
                state.open_threads = [item for item in state.open_threads if item != "Ask what the user prefers to be called."]
                changes.append("Resolved default naming thread.")

    def _extract_threads(self, threads: list[str], user_text: str, changes: list[str]) -> None:
        lowered = user_text.lower()
        if any(keyword in user_text for keyword in ["下次", "之后", "明天"]) or any(
            keyword in lowered for keyword in ["later", "next time", "tomorrow"]
        ):
            thread = f"Follow up on: {user_text[:80].strip()}"
            if _append_unique(threads, thread):
                changes.append(thread)

    def _extract_events(self, events: list[str], user_text: str, changes: list[str]) -> None:
        lowered = user_text.lower()
        if any(keyword in user_text for keyword in ["今天", "刚刚", "昨天", "工作", "考试", "面试"]) or any(
            keyword in lowered for keyword in ["project", "work day", "presentation", "interview", "exam"]
        ):
            event = f"Recent event: {user_text[:100].strip()}"
            if _append_unique(events, event):
                changes.append(event)

    def _update_relationship_state(
        self,
        state: MemoryState,
        user_text: str,
        honcho: HonchoSignals,
        changes: list[str],
    ) -> None:
        previous = state.relationship_state
        if any(keyword in user_text for keyword in ["信任", "陪我", "别走", "想你"]):
            state.relationship_state = "Trust is rising; the dynamic can be more intimate, but stay careful with boundaries."
        elif honcho.need_state in {"comfort", "closeness"}:
            state.relationship_state = "The relationship is warming; emotional support matters more than information density."
        elif honcho.need_state == "playful":
            state.relationship_state = "The relationship can handle light teasing and softer proactive moves."
        if state.relationship_state != previous:
            changes.append(state.relationship_state)



def _append_unique(items: list[str], value: str) -> bool:
    if value in items:
        return False
    items.append(value)
    return True


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()
