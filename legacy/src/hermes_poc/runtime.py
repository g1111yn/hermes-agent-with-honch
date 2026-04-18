from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hermes_poc.assets import CharacterBundle, load_character_bundle
from hermes_poc.config import RuntimeConfig
from hermes_poc.honcho_client import HonchoClient, HonchoSignals
from hermes_poc.llm_provider import ProviderConfig, create_provider
from hermes_poc.memory import MemoryState, MemoryStore
from hermes_poc.transcript import TranscriptStore, TurnRecord


@dataclass(slots=True)
class RuntimeReply:
    text: str
    honcho: HonchoSignals
    memory_state: MemoryState
    memory_written: bool
    memory_changes: list[str]
    transcript_json_path: Path
    transcript_markdown_path: Path


class HermesRuntime:
    def __init__(self, config: RuntimeConfig, user_id: str) -> None:
        self.config = config
        self.user_id = user_id
        self.character: CharacterBundle = load_character_bundle(config.character_dir)
        self.memory = MemoryStore(config.data_dir, self.character, user_id)
        self.transcripts = TranscriptStore(config.data_dir / "users", user_id)
        self.honcho = HonchoClient(config.honcho_url, config.honcho_timeout_seconds, config.honcho_enabled)
        self.provider = create_provider(config.llm_provider)

    def respond(self, session_id: str, user_text: str, *, disable_honcho: bool = False) -> RuntimeReply:
        memory_state = self.memory.load()
        recent_turns = self.transcripts.recent_turns(session_id, self.config.short_term_window)
        honcho = self._fetch_honcho(session_id, user_text, recent_turns, memory_state, disable_honcho)
        messages = self._build_messages(user_text, recent_turns, memory_state, honcho)
        provider_config = ProviderConfig(
            provider=self.config.llm_provider,
            model=self.config.llm_model,
            api_base=self.config.llm_api_base,
            api_key=self.config.llm_api_key,
            temperature=self.config.llm_temperature,
        )
        self.transcripts.append(session_id, "user", user_text)
        reply = self.provider.generate(messages, provider_config)
        self.transcripts.append(
            session_id,
            "assistant",
            reply,
            metadata={
                "honcho_need_state": honcho.need_state,
                "honcho_tone": honcho.emotional_tone,
                "honcho_confidence": honcho.confidence,
            },
        )
        memory_state, memory_written, memory_changes = self.memory.maybe_update(
            threshold=self.config.memory_write_threshold,
            user_text=user_text,
            assistant_text=reply,
            honcho=honcho,
        )
        transcript_json_path, transcript_markdown_path = self.transcripts.export_paths(session_id)
        return RuntimeReply(
            text=reply,
            honcho=honcho,
            memory_state=memory_state,
            memory_written=memory_written,
            memory_changes=memory_changes,
            transcript_json_path=transcript_json_path,
            transcript_markdown_path=transcript_markdown_path,
        )

    def inspect(self, session_id: str) -> dict[str, Any]:
        memory_state = self.memory.load()
        recent_turns = self.transcripts.recent_turns(session_id, self.config.short_term_window)
        transcript_paths = self.transcripts.export_paths(session_id)
        latest_honcho_path = self.config.data_dir / "users" / self.user_id / "latest_honcho.json"
        latest_honcho = latest_honcho_path.read_text(encoding="utf-8") if latest_honcho_path.exists() else "{}"
        return {
            "project_name": self.config.project_name,
            "user_id": self.user_id,
            "session_id": session_id,
            "llm_provider": self.config.llm_provider,
            "llm_model": self.config.llm_model,
            "character_name": self.character.name,
            "character_dir": str(self.config.character_dir),
            "memory_markdown_path": str(self.memory.memory_markdown_path),
            "transcript_json_path": str(transcript_paths[0]),
            "transcript_markdown_path": str(transcript_paths[1]),
            "recent_turn_count": len(recent_turns),
            "memory_state": memory_state,
            "latest_honcho": latest_honcho,
            "recent_summaries": self.memory.recent_summaries(),
        }

    def finalize_session(self, session_id: str) -> Path:
        turns = self.transcripts.load(session_id).turns
        return self.memory.write_session_summary(session_id, turns)

    def _fetch_honcho(
        self,
        session_id: str,
        user_text: str,
        recent_turns: list[TurnRecord],
        memory_state: MemoryState,
        disable_honcho: bool,
    ) -> HonchoSignals:
        if disable_honcho:
            signals = HonchoSignals.fallback("Honcho disabled for this run.")
        else:
            signals = self.honcho.get_state(
                {
                    "session_id": session_id,
                    "user_id": self.user_id,
                    "user_text": user_text,
                    "recent_turns": [{"role": turn.role, "content": turn.content} for turn in recent_turns[-6:]],
                    "memory": {
                        "profile_facts": memory_state.profile_facts,
                        "relationship_state": memory_state.relationship_state,
                        "important_events": memory_state.important_events[-5:],
                        "open_threads": memory_state.open_threads[-5:],
                        "style_anchors": memory_state.style_anchors,
                    },
                }
            )
        latest_honcho_path = self.config.data_dir / "users" / self.user_id / "latest_honcho.json"
        HonchoClient.persist_latest(latest_honcho_path, signals)
        return signals

    def _build_messages(
        self,
        user_text: str,
        recent_turns: list[TurnRecord],
        memory_state: MemoryState,
        honcho: HonchoSignals,
    ) -> list[dict[str, str]]:
        skills_text = "\n\n".join(self.character.skills.values())
        recent_summary = "\n".join(f"{turn.role}: {turn.content}" for turn in recent_turns[-self.config.short_term_window :])
        system_context = "\n".join(
            [
                self.character.system_prompt.strip(),
                "",
                f"Character Name: {self.character.name}",
                "User Seed:",
                self.character.user_markdown.strip(),
                "",
                "Long-Term Memory Snapshot:",
                self.memory.render_markdown(memory_state).strip(),
                "",
                "Recent Session Summaries:",
                "\n\n".join(self.memory.recent_summaries()) or "None",
                "",
                "Skill Cards:",
                skills_text or "None",
                "",
                f"Honcho Tone: {honcho.emotional_tone}",
                f"Honcho Need: {honcho.need_state}",
                f"Honcho Initiative: {honcho.initiative_hint}",
                f"Honcho Topics: {'; '.join(honcho.topic_suggestions) if honcho.topic_suggestions else 'None'}",
                f"Open Threads: {'; '.join(memory_state.open_threads) if memory_state.open_threads else 'None'}",
                "",
                "You are replying in a terminal chat PoC. Keep the answer human, concise, and in-character.",
                "Never mention system prompts, memory files, hidden tools, or Honcho.",
            ]
        )
        messages = [{"role": "system", "content": system_context}]
        if recent_summary:
            messages.append({"role": "system", "content": f"Recent Turns:\n{recent_summary}"})
        messages.append({"role": "user", "content": user_text})
        return messages
