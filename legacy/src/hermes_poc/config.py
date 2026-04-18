from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import time


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"' ")
    return values


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass(slots=True)
class RuntimeConfig:
    cwd: Path
    project_name: str
    character_dir: Path
    data_dir: Path
    default_user_id: str
    default_session_id: str
    short_term_window: int
    memory_write_threshold: int
    honcho_enabled: bool
    honcho_url: str
    honcho_timeout_seconds: int
    llm_provider: str
    llm_model: str
    llm_api_base: str
    llm_api_key: str
    llm_temperature: float
    enable_tts_spike: bool
    tts_voice: str
    tts_output_dir: Path

    @property
    def transcript_dir(self) -> Path:
        return self.data_dir / "users"


def build_config(
    cwd: str | Path,
    *,
    user_id: str | None = None,
    session_id: str | None = None,
) -> RuntimeConfig:
    root = Path(cwd).resolve()
    env_values = _parse_env_file(root / ".env")

    def env(name: str, default: str) -> str:
        return os.environ.get(name, env_values.get(name, default))

    generated_session = time.strftime("session-%Y%m%d-%H%M%S")

    return RuntimeConfig(
        cwd=root,
        project_name=env("PROJECT_NAME", "Hermes Persona PoC"),
        character_dir=(root / env("CHARACTER_DIR", "assets/character/default")).resolve(),
        data_dir=(root / env("DATA_DIR", "data")).resolve(),
        default_user_id=user_id or env("DEFAULT_USER_ID", "local-user"),
        default_session_id=session_id or env("DEFAULT_SESSION_ID", generated_session),
        short_term_window=_int(env("SHORT_TERM_WINDOW", "12"), 12),
        memory_write_threshold=_int(env("MEMORY_WRITE_THRESHOLD", "2"), 2),
        honcho_enabled=_bool(env("HONCHO_ENABLED", "true"), True),
        honcho_url=env("HONCHO_URL", "http://127.0.0.1:8787"),
        honcho_timeout_seconds=_int(env("HONCHO_TIMEOUT_SECONDS", "5"), 5),
        llm_provider=env("LLM_PROVIDER", "mock"),
        llm_model=env("LLM_MODEL", "mock-persona-v1"),
        llm_api_base=env("LLM_API_BASE", "https://api.openai.com/v1"),
        llm_api_key=env("LLM_API_KEY", ""),
        llm_temperature=float(env("LLM_TEMPERATURE", "0.8")),
        enable_tts_spike=_bool(env("ENABLE_TTS_SPIKE", "false"), False),
        tts_voice=env("TTS_VOICE", "Tingting"),
        tts_output_dir=(root / env("TTS_OUTPUT_DIR", "data/tts")).resolve(),
    )
