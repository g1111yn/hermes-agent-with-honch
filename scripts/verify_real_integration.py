#!/usr/bin/env python3
"""Smoke-check the real Hermes + Honcho integration."""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HERMES_ROOT = Path.home() / ".hermes" / "hermes-agent"
HERMES_PYTHON = HERMES_ROOT / "venv" / "bin" / "python"


def _fetch_json(url: str) -> dict:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _run(cmd: list[str], *, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout.strip()


def main() -> int:
    report: dict[str, object] = {}

    report["proxy_health"] = _fetch_json("http://127.0.0.1:11435/healthz")
    report["honcho_health"] = _fetch_json("http://127.0.0.1:8000/health")
    report["memory_status"] = _run(["hermes", "memory", "status"])
    report["docker_ps"] = _run(["docker", "compose", "ps"], cwd=PROJECT_ROOT)
    report["sdk_sessions"] = _run(
        [
            str(HERMES_PYTHON),
            "-c",
            (
                "from plugins.memory.honcho.client import HonchoClientConfig, "
                "get_honcho_client, reset_honcho_client; "
                "reset_honcho_client(); "
                "client=get_honcho_client(HonchoClientConfig.from_global_config()); "
                "sessions=client.sessions(size=20); "
                "print('\\n'.join(s.id for s in sessions.items))"
            ),
        ],
        cwd=HERMES_ROOT,
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
