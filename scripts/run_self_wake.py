#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT_ROOT = Path(os.getenv("HERMES_AGENT_ROOT", ROOT / "runtime" / "hermes-agent")).resolve()
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from agent.self_wake import SelfWakeService  # noqa: E402


def _default_role_id() -> str:
    candidates = [
        os.getenv("HERMES_SELF_WAKE_ROLE_ID", "").strip(),
        os.getenv("API_SERVER_MODEL_NAME", "").strip(),
    ]
    for value in candidates:
        if value:
            return value
    return "caleb"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one Hermes self-wake cycle for a role profile.")
    parser.add_argument("--role", default=_default_role_id(), help="Role/profile id to run")
    parser.add_argument("--resume", action="store_true", help="Resume a previously interrupted self-wake")
    args = parser.parse_args()

    result = SelfWakeService(args.role).run(resume=bool(args.resume))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
