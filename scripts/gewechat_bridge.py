#!/usr/bin/env python3
"""Minimal operator CLI for a local Gewechat bridge deployment."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
ENV_INTERFACE = ROOT / "deploy" / ".env.interface"
DEFAULT_HOST_API_BASE = "http://127.0.0.1:2531/v2/api"


def load_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.is_file():
        return data
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def resolve_default(key: str, fallback: str = "") -> str:
    if key in os.environ and os.environ[key].strip():
        return os.environ[key].strip()
    env_file = load_env_file(ENV_INTERFACE)
    return env_file.get(key, fallback).strip() or fallback


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-base",
        default=DEFAULT_HOST_API_BASE,
        help=f"Bridge API base URL. Default: {DEFAULT_HOST_API_BASE}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("get-token", help="Request a fresh Gewechat token")

    qr = subparsers.add_parser("get-qr", help="Request a login QR code")
    qr.add_argument("--token", default=resolve_default("WECHAT_BRIDGE_TOKEN"))
    qr.add_argument("--app-id", default=resolve_default("WECHAT_BRIDGE_APP_ID"))
    qr.add_argument("--qr-file", help="Optional path to write the QR image PNG")

    check_login = subparsers.add_parser("check-login", help="Poll login status")
    check_login.add_argument("--token", default=resolve_default("WECHAT_BRIDGE_TOKEN"))
    check_login.add_argument("--app-id", default=resolve_default("WECHAT_BRIDGE_APP_ID"))
    check_login.add_argument("--uuid", required=True, help="UUID returned by get-qr")

    set_callback = subparsers.add_parser("set-callback", help="Register gateway callback")
    set_callback.add_argument("--token", default=resolve_default("WECHAT_BRIDGE_TOKEN"))
    set_callback.add_argument("--app-id", default=resolve_default("WECHAT_BRIDGE_APP_ID"))
    set_callback.add_argument(
        "--callback-url",
        default=resolve_default(
            "WECHAT_BRIDGE_CALLBACK_URL",
            "http://wechat-gateway:8080/bridges/gewechat/callback",
        ),
    )

    online = subparsers.add_parser("check-online", help="Check bridge login state")
    online.add_argument("--token", default=resolve_default("WECHAT_BRIDGE_TOKEN"))
    online.add_argument("--app-id", default=resolve_default("WECHAT_BRIDGE_APP_ID"))

    return parser


def request_json(
    api_base: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    token: str = "",
) -> dict[str, Any]:
    body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-GEWE-TOKEN"] = token
    request = urllib.request.Request(
        f"{api_base.rstrip('/')}{path}",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code} for {path}: {detail}") from exc


def require_arg(name: str, value: str) -> str:
    value = value.strip()
    if value:
        return value
    raise SystemExit(f"Missing required value: {name}")


def main() -> int:
    args = build_parser().parse_args()
    api_base = args.api_base.rstrip("/")

    if args.command == "get-token":
        response = request_json(api_base, "/tools/getTokenId")
        print(json.dumps(response, ensure_ascii=False, indent=2))
        token = str(response.get("data") or "").strip()
        if token:
            print(f"\nWECHAT_BRIDGE_TOKEN={token}")
        return 0

    if args.command == "get-qr":
        token = require_arg("token", args.token)
        response = request_json(
            api_base,
            "/login/getLoginQrCode",
            {"appId": args.app_id.strip()},
            token=token,
        )
        print(json.dumps(response, ensure_ascii=False, indent=2))
        data = response.get("data") or {}
        app_id = str(data.get("appId") or args.app_id or "").strip()
        if app_id:
            print(f"\nWECHAT_BRIDGE_APP_ID={app_id}")
        qr_file = (args.qr_file or "").strip()
        qr_base64 = str(data.get("qrImgBase64") or "").strip()
        if qr_file and qr_base64:
            Path(qr_file).write_bytes(base64.b64decode(qr_base64))
            print(f"QR image written to {qr_file}")
        return 0

    if args.command == "check-login":
        token = require_arg("token", args.token)
        app_id = require_arg("app-id", args.app_id)
        response = request_json(
            api_base,
            "/login/checkLogin",
            {"appId": app_id, "uuid": args.uuid},
            token=token,
        )
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return 0

    if args.command == "set-callback":
        token = require_arg("token", args.token)
        payload: dict[str, Any] = {
            "token": token,
            "callbackUrl": require_arg("callback-url", args.callback_url),
        }
        if args.app_id.strip():
            payload["appId"] = args.app_id.strip()
        response = request_json(api_base, "/tools/setCallback", payload, token=token)
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return 0

    if args.command == "check-online":
        token = require_arg("token", args.token)
        app_id = require_arg("app-id", args.app_id)
        response = request_json(
            api_base,
            "/login/checkOnline",
            {"appId": app_id},
            token=token,
        )
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return 0

    raise SystemExit(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
