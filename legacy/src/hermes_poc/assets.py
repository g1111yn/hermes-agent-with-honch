from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


def parse_markdown_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = "default"
    sections[current] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            current = re.sub(r"[^a-z0-9]+", "-", line[3:].strip().lower()).strip("-") or "default"
            sections.setdefault(current, [])
            continue
        if line.startswith("- "):
            sections.setdefault(current, []).append(line[2:].strip())
        elif line:
            sections.setdefault(current, []).append(line)
    return sections


@dataclass(slots=True)
class CharacterBundle:
    name: str
    system_prompt: str
    user_markdown: str
    memory_markdown: str
    user_sections: dict[str, list[str]]
    memory_sections: dict[str, list[str]]
    skills: dict[str, str]


def load_character_bundle(character_dir: str | Path) -> CharacterBundle:
    root = Path(character_dir).resolve()
    system_prompt = (root / "SYSTEM_PROMPT.md").read_text(encoding="utf-8")
    user_markdown = (root / "USER.md").read_text(encoding="utf-8")
    memory_markdown = (root / "MEMORY.md").read_text(encoding="utf-8")
    skills: dict[str, str] = {}
    skills_dir = root / "skills"
    if skills_dir.exists():
        for path in sorted(skills_dir.glob("*.md")):
            skills[path.stem] = path.read_text(encoding="utf-8")
    sections = parse_markdown_sections(user_markdown)
    memory_sections = parse_markdown_sections(memory_markdown)
    name = next(iter(sections.get("identity", ["Qiyao"]))).split(":", 1)[-1].strip()
    return CharacterBundle(
        name=name or "Qiyao",
        system_prompt=system_prompt,
        user_markdown=user_markdown,
        memory_markdown=memory_markdown,
        user_sections=sections,
        memory_sections=memory_sections,
        skills=skills,
    )
