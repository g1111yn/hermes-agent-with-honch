#!/usr/bin/env python3
"""OpenAI-compatible proxy that routes Honcho LLM traffic through Hermes."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import sys
import time
import uuid
from dataclasses import asdict, is_dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


HERMES_AGENT_ROOT = Path(
    os.environ.get("HERMES_AGENT_ROOT", str(Path.home() / ".hermes" / "hermes-agent"))
).expanduser()
if str(HERMES_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(HERMES_AGENT_ROOT))

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolve_proxy_hermes_home() -> Path:
    explicit_home = os.environ.get("HERMES_HOME", "").strip()
    if explicit_home:
        return Path(explicit_home).expanduser()

    hermes_root = Path.home() / ".hermes"
    requested_profile = os.environ.get("HERMES_PROFILE", "").strip()
    if requested_profile and requested_profile != "default":
        return (hermes_root / "profiles" / requested_profile).expanduser()

    active_profile_path = hermes_root / "active_profile"
    try:
        active_profile = active_profile_path.read_text(encoding="utf-8").strip()
    except OSError:
        active_profile = ""
    if active_profile and active_profile != "default":
        return (hermes_root / "profiles" / active_profile).expanduser()
    return hermes_root.expanduser()


HERMES_HOME = _resolve_proxy_hermes_home()
os.environ["HERMES_HOME"] = str(HERMES_HOME)

from hermes_cli.env_loader import load_hermes_dotenv

load_hermes_dotenv(hermes_home=HERMES_HOME, project_env=PROJECT_ROOT / ".env")

from agent.auxiliary_client import extract_content_or_reasoning, resolve_provider_client
from hermes_cli.config import load_config
from hermes_cli.runtime_provider import resolve_runtime_provider


def _runtime_config() -> dict[str, str]:
    cfg = load_config()
    model_cfg = cfg.get("model", {}) if isinstance(cfg, dict) else {}
    requested = model_cfg.get("provider")
    runtime = resolve_runtime_provider(requested=requested)
    return {
        "provider": str(runtime.get("provider") or requested or "auto").strip(),
        "model": str(model_cfg.get("default") or model_cfg.get("model") or "").strip(),
        "base_url": str(runtime.get("base_url") or "").strip(),
        "api_key": str(runtime.get("api_key") or "").strip(),
        "api_mode": str(runtime.get("api_mode") or "").strip(),
    }


def _runtime_public_view(runtime: dict[str, str]) -> dict[str, str]:
    return {
        "provider": runtime.get("provider", ""),
        "model": runtime.get("model", ""),
        "base_url": runtime.get("base_url", ""),
        "api_mode": runtime.get("api_mode", ""),
        "api_key": "***" if runtime.get("api_key") else "",
    }


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if hasattr(value, "__dict__"):
        return {
            key: inner
            for key, inner in vars(value).items()
            if not key.startswith("_")
        }
    return str(value)


def _append_json_instruction(messages: list[dict[str, Any]], response_format: Any) -> list[dict[str, Any]]:
    if not response_format:
        return messages

    messages = copy.deepcopy(messages)
    schema_hint = "Respond with valid JSON only."
    if isinstance(response_format, dict):
        fmt_type = str(response_format.get("type") or "").lower()
        if fmt_type == "json_schema":
            schema = response_format.get("json_schema") or {}
            schema_name = schema.get("name") or "schema"
            schema_body = json.dumps(schema.get("schema") or {}, ensure_ascii=False)
            schema_hint = (
                f"Respond with valid JSON only. Match the JSON schema named "
                f"{schema_name}: {schema_body}"
            )
        elif fmt_type == "json_object":
            schema_hint = "Respond with a valid JSON object only."

    if messages and messages[0].get("role") == "system":
        content = messages[0].get("content") or ""
        messages[0]["content"] = f"{content}\n\n{schema_hint}".strip()
    else:
        messages.insert(0, {"role": "system", "content": schema_hint})
    return messages


def _normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize OpenAI chat messages into a Codex-compatible subset."""
    normalized: list[dict[str, Any]] = []
    for raw in messages:
        if not isinstance(raw, dict):
            continue
        msg = copy.deepcopy(raw)
        role = str(msg.get("role") or "user").lower()
        content = msg.get("content")

        if role == "tool":
            tool_name = msg.get("name") or msg.get("tool_name") or "tool"
            if isinstance(content, list):
                content = json.dumps(content, ensure_ascii=False)
            normalized.append(
                {
                    "role": "user",
                    "content": f"Tool result from {tool_name}:\n{content or ''}".strip(),
                }
            )
            continue

        if role == "assistant" and msg.get("tool_calls"):
            summaries: list[str] = []
            for tool_call in msg.get("tool_calls") or []:
                function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
                name = function.get("name") or "tool"
                arguments = function.get("arguments") or "{}"
                summaries.append(f"{name}({arguments})")
            summary_text = "Assistant requested tool calls: " + "; ".join(summaries)
            if content:
                if isinstance(content, list):
                    content = json.dumps(content, ensure_ascii=False)
                summary_text = f"{summary_text}\n\nAssistant note:\n{content}"
            normalized.append({"role": "assistant", "content": summary_text})
            continue

        if isinstance(content, list):
            content = json.dumps(content, ensure_ascii=False)
        normalized.append({"role": role, "content": content})
    return normalized


def _estimate_tokens(payload: Any) -> int:
    if isinstance(payload, str):
        return max(1, len(payload) // 4)
    if isinstance(payload, list):
        return sum(_estimate_tokens(item) for item in payload)
    if isinstance(payload, dict):
        return sum(_estimate_tokens(value) for value in payload.values())
    return _estimate_tokens(str(payload))


def _hashed_embedding(text: str, *, dims: int = 1536) -> list[float]:
    vec = [0.0] * dims
    tokens = re.findall(r"[\w]+", text.lower())
    if not tokens:
        tokens = ["__empty__"]

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        for offset in (0, 8, 16):
            idx = int.from_bytes(digest[offset:offset + 4], "big") % dims
            sign = 1.0 if digest[offset + 4] % 2 == 0 else -1.0
            weight = 1.0 + (digest[offset + 5] / 255.0)
            vec[idx] += sign * weight

    norm = math.sqrt(sum(value * value for value in vec)) or 1.0
    return [value / norm for value in vec]


def _serialize_tool_calls(raw_tool_calls: Any) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for tool_call in raw_tool_calls or []:
        function = getattr(tool_call, "function", None)
        serialized.append(
            {
                "id": getattr(tool_call, "id", "") or f"call_{uuid.uuid4().hex}",
                "type": "function",
                "function": {
                    "name": getattr(function, "name", "") if function else "",
                    "arguments": getattr(function, "arguments", "{}") if function else "{}",
                },
            }
        )
    return serialized


def _chat_completion_payload(body: dict[str, Any]) -> dict[str, Any]:
    runtime = _runtime_config()
    client, resolved_model = resolve_provider_client(
        "auto",
        model=runtime.get("model") or body.get("model"),
        async_mode=False,
        main_runtime=runtime,
    )
    if client is None:
        raise RuntimeError("Hermes runtime client could not be resolved.")

    requested_model = str(body.get("model") or runtime.get("model") or resolved_model or "")
    messages = body.get("messages") or []
    if not isinstance(messages, list):
        raise ValueError("messages must be a list")

    messages = _normalize_messages(messages)
    messages = _append_json_instruction(messages, body.get("response_format"))
    kwargs: dict[str, Any] = {
        "model": runtime.get("model") or requested_model,
        "messages": messages,
    }
    max_tokens = body.get("max_completion_tokens", body.get("max_tokens"))
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if body.get("tools"):
        kwargs["tools"] = body["tools"]
    if body.get("tool_choice") is not None:
        kwargs["tool_choice"] = body["tool_choice"]
    if body.get("temperature") is not None and "gpt-5" not in requested_model:
        kwargs["temperature"] = body["temperature"]

    response = client.chat.completions.create(**kwargs)
    choice = response.choices[0]
    message = choice.message
    tool_calls = _serialize_tool_calls(getattr(message, "tool_calls", None))
    content = extract_content_or_reasoning(response)
    usage = getattr(response, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else _estimate_tokens(messages)
    completion_tokens = getattr(usage, "completion_tokens", 0) if usage else _estimate_tokens(content)
    total_tokens = getattr(usage, "total_tokens", 0) if usage else prompt_tokens + completion_tokens

    payload: dict[str, Any] = {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": requested_model or runtime.get("model") or "",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None if tool_calls and not content else content,
                    **({"tool_calls": tool_calls} if tool_calls else {}),
                },
                "finish_reason": getattr(choice, "finish_reason", None) or ("tool_calls" if tool_calls else "stop"),
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        },
    }
    return payload


def _stream_chat_completion(handler: BaseHTTPRequestHandler, body: dict[str, Any]) -> None:
    payload = _chat_completion_payload(body)
    choice = payload["choices"][0]
    message = choice["message"]
    content = message.get("content") or ""
    tool_calls = message.get("tool_calls") or []
    model = payload["model"]
    created = payload["created"]
    chunk_id = payload["id"]

    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "keep-alive")
    handler.end_headers()

    first_delta = {"role": "assistant"}
    if content:
        first_delta["content"] = content
    if tool_calls:
        first_delta["tool_calls"] = tool_calls

    start_chunk = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": first_delta, "finish_reason": None}],
    }
    done_chunk = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": choice["finish_reason"]}],
    }

    for chunk in (start_chunk, done_chunk):
        handler.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8"))
        handler.wfile.flush()
    handler.wfile.write(b"data: [DONE]\n\n")
    handler.wfile.flush()


class HermesProxyHandler(BaseHTTPRequestHandler):
    server_version = "HermesModelProxy/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write(f"[hermes-model-proxy] {format % args}\n")

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON body: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _send_json(self, payload: dict[str, Any], *, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        runtime = _runtime_config()
        if self.path in ("/health", "/healthz", "/v1/health"):
            self._send_json({"status": "ok", "runtime": _runtime_public_view(runtime)})
            return
        if self.path == "/v1/models":
            model = runtime.get("model") or "unknown"
            self._send_json(
                {
                    "object": "list",
                    "data": [
                        {
                            "id": model,
                            "object": "model",
                            "created": int(time.time()),
                            "owned_by": "hermes",
                        }
                    ],
                }
            )
            return
        self._send_json({"error": f"unknown path: {self.path}"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        try:
            body = self._read_json()
            if self.path == "/v1/chat/completions":
                if body.get("stream"):
                    _stream_chat_completion(self, body)
                else:
                    self._send_json(_chat_completion_payload(body))
                return
            if self.path == "/v1/embeddings":
                raw_input = body.get("input", "")
                inputs = raw_input if isinstance(raw_input, list) else [raw_input]
                inputs = [item if isinstance(item, str) else json.dumps(item, ensure_ascii=False) for item in inputs]
                model = str(body.get("model") or "hermes-lexical-1536")
                data = [
                    {
                        "object": "embedding",
                        "index": idx,
                        "embedding": _hashed_embedding(text),
                    }
                    for idx, text in enumerate(inputs)
                ]
                usage = sum(_estimate_tokens(text) for text in inputs)
                self._send_json(
                    {
                        "object": "list",
                        "data": data,
                        "model": model,
                        "usage": {"prompt_tokens": usage, "total_tokens": usage},
                    }
                )
                return
            self._send_json({"error": f"unknown path: {self.path}"}, status=HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)


def main() -> None:
    host = os.environ.get("HERMES_PROXY_HOST", "127.0.0.1")
    port = int(os.environ.get("HERMES_PROXY_PORT", "11435"))
    server = ThreadingHTTPServer((host, port), HermesProxyHandler)
    print(
        json.dumps(
            {
                "status": "listening",
                "host": host,
                "port": port,
                "hermes_agent_root": str(HERMES_AGENT_ROOT),
                "hermes_home": str(HERMES_HOME),
                "runtime": _runtime_public_view(_runtime_config()),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
