from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .config import GatewayConfig
from .dedupe import DedupeStore
from .gewechat import (
    GewechatClient,
    GewechatClientConfig,
    make_dedupe_key,
    parse_gewechat_callback,
)
from .hermes_client import HermesClient, HermesClientConfig
from .messages import segment_messages


class InboundMessage(BaseModel):
    conversation_id: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


config = GatewayConfig.from_env()
hermes_client = HermesClient(
    HermesClientConfig(
        base_url=config.hermes_api_base,
        api_key=config.hermes_api_key,
        model_name=config.hermes_model_name,
    )
)
bridge_client = GewechatClient(
    GewechatClientConfig(
        api_base=config.bridge_api_base,
        app_id=config.bridge_app_id,
        token=config.bridge_token,
        callback_url=config.bridge_callback_url,
        auto_register_callback=config.bridge_auto_register_callback,
    )
)
dedupe_store = DedupeStore(
    Path(config.dedupe_store_path),
    ttl_seconds=config.dedupe_ttl_seconds,
)

app = FastAPI(title="wechat-gateway", version="0.2.0")


@app.on_event("startup")
async def register_bridge_callback() -> None:
    if not config.bridge_auto_register_callback:
        return
    if config.bridge_name.lower() != "gewechat":
        return
    if not config.bridge_app_id or not config.bridge_callback_url:
        return
    await asyncio.to_thread(bridge_client.register_callback)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "bridge_mode": config.bridge_mode,
        "bridge_name": config.bridge_name,
        "bridge_api_base": config.bridge_api_base,
        "hermes_api_base": config.hermes_api_base,
    }


@app.post("/wechat/v1/messages/inbound")
def receive_message(
    message: InboundMessage,
    x_gateway_token: str | None = Header(default=None),
) -> dict[str, Any]:
    if config.gateway_token and x_gateway_token != config.gateway_token:
        raise HTTPException(status_code=401, detail="invalid gateway token")

    raw_text = hermes_client.send_message(
        conversation_id=message.conversation_id,
        text=message.text,
        metadata={
            "platform": "wechat",
            "bridge_mode": config.bridge_mode,
            "bridge_name": config.bridge_name,
            "user_id": message.user_id,
            **message.metadata,
        },
    )
    outbound = [asdict(item) for item in segment_messages(raw_text)]
    return {
        "conversation_id": message.conversation_id,
        "messages": outbound,
        "raw_text": raw_text,
    }


@app.post("/bridges/gewechat/callback")
async def receive_gewechat_callback(payload: dict[str, Any]) -> dict[str, Any]:
    event = parse_gewechat_callback(payload)
    if event is None:
        return {"ok": True, "ignored": True, "reason": "unsupported_or_empty"}

    dedupe_key = make_dedupe_key(payload)
    if dedupe_key and dedupe_store.seen(dedupe_key):
        return {"ok": True, "ignored": True, "reason": "duplicate"}

    raw_text = await asyncio.to_thread(
        hermes_client.send_message,
        conversation_id=event.conversation_id,
        text=event.text,
        metadata=event.metadata,
    )
    outbound = segment_messages(raw_text)

    to_wxid = str(event.metadata.get("group_id") or event.metadata.get("from_user") or event.user_id).strip()
    ats = str(event.metadata.get("speaker_id") or "").strip() if event.metadata.get("is_group") else ""
    sent = []
    for index, item in enumerate(outbound):
        if index:
            await asyncio.sleep(config.chunk_delay_seconds)
        response = await asyncio.to_thread(
            bridge_client.send_text,
            to_wxid=to_wxid,
            content=item.content,
            ats=ats,
        )
        sent.append(response)

    return {
        "ok": True,
        "conversation_id": event.conversation_id,
        "sent_count": len(outbound),
        "raw_text": raw_text,
        "messages": [asdict(item) for item in outbound],
        "bridge_responses": sent,
    }
