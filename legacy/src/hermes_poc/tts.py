from __future__ import annotations

import datetime as dt
from pathlib import Path
import subprocess


class TTSClient:
    def __init__(self, voice: str, output_dir: Path) -> None:
        self.voice = voice
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def synthesize(self, text: str, stem: str | None = None) -> Path:
        filename = stem or dt.datetime.now().strftime("tts-%Y%m%d-%H%M%S")
        output_path = self.output_dir / f"{filename}.aiff"
        subprocess.run(
            ["say", "-v", self.voice, "-o", str(output_path), text],
            check=True,
        )
        return output_path
