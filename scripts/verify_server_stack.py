#!/usr/bin/env python3
"""Basic verification for the semi-containerized server stack."""

from __future__ import annotations

import json
import urllib.request


def _fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    report = {
        "wechat_gateway": _fetch_json("http://127.0.0.1:8081/health"),
        "honcho": _fetch_json("http://127.0.0.1:8000/health"),
        "hermes_proxy": _fetch_json("http://127.0.0.1:11435/healthz"),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
