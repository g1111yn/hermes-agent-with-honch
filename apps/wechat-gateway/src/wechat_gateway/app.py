from __future__ import annotations

import asyncio
import time as _time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .bridge import BridgeClientConfig, build_bridge_client
from .bindings import BindingStore
from .config import GatewayConfig
from .dedupe import DedupeStore
from .gewechat import (
    GewechatInboundEvent,
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


class OutboundMessageRequest(BaseModel):
    text: str = Field(..., min_length=1)
    to_wxid: str = Field(default="")
    ats: str = Field(default="")
    source: str = Field(default="manual")
    proactive: bool = Field(default=False)


config = GatewayConfig.from_env()
hermes_client = HermesClient(
    HermesClientConfig(
        base_url=config.hermes_api_base,
        api_key=config.hermes_api_key,
        model_name=config.hermes_model_name,
    )
)
bridge_client = build_bridge_client(
    BridgeClientConfig(
        driver=config.bridge_driver,
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
binding_store = BindingStore(Path(config.binding_store_path))

app = FastAPI(title="wechat-gateway", version="0.2.0")


# ---------------------------------------------------------------------------
# Debounce buffer: accumulate rapid-fire messages per conversation, flush
# after a silence window (default 3.58s) or a hard max-wait ceiling (15s).
# ---------------------------------------------------------------------------

@dataclass
class _PendingBatch:
    events: list[GewechatInboundEvent] = field(default_factory=list)
    image_payloads: list[dict[str, Any]] = field(default_factory=list)
    first_arrived: float = 0.0
    timer: asyncio.Task[None] | None = None


_debounce_buckets: dict[str, _PendingBatch] = {}
_debounce_lock = asyncio.Lock()


async def _debounce_enqueue(event: GewechatInboundEvent, raw_payload: dict[str, Any]) -> None:
    """Add an event to the debounce buffer; schedule or reset the flush timer."""
    key = event.conversation_id
    now = _time.monotonic()

    async with _debounce_lock:
        batch = _debounce_buckets.get(key)
        if batch is None:
            batch = _PendingBatch(first_arrived=now)
            _debounce_buckets[key] = batch

        batch.events.append(event)
        image_msg_id = str(event.metadata.get("image_msg_id") or "").strip()
        if image_msg_id:
            batch.image_payloads.append({
                "image_msg_id": image_msg_id,
                "app_id": str(event.metadata.get("app_id") or "").strip() or None,
            })

        if batch.timer is not None:
            batch.timer.cancel()

        elapsed = now - batch.first_arrived
        remaining_max = max(0.1, config.debounce_max_wait_seconds - elapsed)
        delay = min(config.debounce_seconds, remaining_max)
        batch.timer = asyncio.create_task(_debounce_flush_after(key, delay))


async def _debounce_flush_after(key: str, delay: float) -> None:
    await asyncio.sleep(delay)
    async with _debounce_lock:
        batch = _debounce_buckets.pop(key, None)
    if batch and batch.events:
        await _process_batched_events(batch)


async def _process_batched_events(batch: _PendingBatch) -> None:
    """Merge buffered events into one agent call."""
    events = batch.events
    last_event = events[-1]
    merged_text = "\n".join(e.text for e in events if e.text)
    merged_metadata = {**last_event.metadata}

    for ev in events:
        asyncio.create_task(asyncio.to_thread(
            hermes_client.report_interaction,
            role_id=config.hermes_model_name,
            direction="inbound",
            text=ev.text,
            conversation_id=ev.conversation_id,
            platform="wechat",
            metadata=ev.metadata,
        ))

    image_bytes: bytes | None = None
    if batch.image_payloads:
        last_img = batch.image_payloads[-1]
        image_bytes = await asyncio.to_thread(
            bridge_client.download_image,
            msg_id=last_img["image_msg_id"],
            app_id=last_img["app_id"],
        )

    raw_text = await asyncio.to_thread(
        hermes_client.send_message,
        conversation_id=last_event.conversation_id,
        text=merged_text,
        metadata=merged_metadata,
        image_bytes=image_bytes,
    )
    outbound = segment_messages(raw_text)

    to_wxid = str(merged_metadata.get("group_id") or merged_metadata.get("from_user") or last_event.user_id).strip()
    ats = str(merged_metadata.get("speaker_id") or "").strip() if merged_metadata.get("is_group") else ""
    binding_store.save_last_target(
        model_name=config.hermes_model_name,
        target={
            "conversation_id": last_event.conversation_id,
            "user_id": last_event.user_id,
            "to_wxid": to_wxid,
            "ats": ats,
            "is_group": bool(merged_metadata.get("is_group")),
            "updated_from": "gewechat_callback",
        },
    )
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
    await asyncio.to_thread(
        hermes_client.report_interaction,
        role_id=config.hermes_model_name,
        direction="outbound",
        text=raw_text,
        conversation_id=last_event.conversation_id,
        platform="wechat",
        metadata={
            "to_wxid": to_wxid,
            "ats": ats,
            "source": "reply",
            **merged_metadata,
        },
        sent=bool(sent),
        proactive=False,
    )


@app.on_event("startup")
async def register_bridge_callback() -> None:
    if not config.bridge_auto_register_callback:
        return
    if not config.bridge_callback_url:
        return
    await asyncio.to_thread(bridge_client.register_callback)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "bridge_driver": config.bridge_driver,
        "bridge_mode": config.bridge_mode,
        "bridge_name": config.bridge_name,
        "bridge_api_base": config.bridge_api_base,
        "hermes_api_base": config.hermes_api_base,
    }


@app.get("/wechat/v1/bindings/last")
def get_last_binding(x_gateway_token: str | None = Header(default=None)) -> dict[str, Any]:
    if config.gateway_token and x_gateway_token != config.gateway_token:
        raise HTTPException(status_code=401, detail="invalid gateway token")
    target = binding_store.get_last_target(config.hermes_model_name)
    return {
        "ok": True,
        "model": config.hermes_model_name,
        "target": target,
    }


@app.post("/wechat/v1/messages/outbound")
async def send_outbound_message(
    request: OutboundMessageRequest,
    x_gateway_token: str | None = Header(default=None),
) -> dict[str, Any]:
    if config.gateway_token and x_gateway_token != config.gateway_token:
        raise HTTPException(status_code=401, detail="invalid gateway token")

    bound_target = binding_store.get_last_target(config.hermes_model_name) or {}
    to_wxid = str(request.to_wxid or bound_target.get("to_wxid") or "").strip()
    if not to_wxid:
        raise HTTPException(status_code=400, detail="missing outbound target")

    ats = str(request.ats or bound_target.get("ats") or "").strip()
    outbound = segment_messages(request.text)
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
    await asyncio.to_thread(
        hermes_client.report_interaction,
        role_id=config.hermes_model_name,
        direction="outbound",
        text=request.text,
        conversation_id=str(bound_target.get("conversation_id") or ""),
        platform="wechat",
        metadata={
            "to_wxid": to_wxid,
            "ats": ats,
            "source": request.source,
        },
        sent=bool(sent),
        proactive=bool(request.proactive),
    )

    return {
        "ok": True,
        "model": config.hermes_model_name,
        "to_wxid": to_wxid,
        "sent_count": len(outbound),
        "messages": [asdict(item) for item in outbound],
        "bridge_responses": sent,
    }


@app.post("/wechat/v1/messages/inbound")
def receive_message(
    message: InboundMessage,
    x_gateway_token: str | None = Header(default=None),
) -> dict[str, Any]:
    if config.gateway_token and x_gateway_token != config.gateway_token:
        raise HTTPException(status_code=401, detail="invalid gateway token")

    hermes_client.report_interaction(
        role_id=config.hermes_model_name,
        direction="inbound",
        text=message.text,
        conversation_id=message.conversation_id,
        platform="wechat",
        metadata=message.metadata,
    )
    to_wxid = str(
        message.metadata.get("to_wxid")
        or message.metadata.get("group_id")
        or message.metadata.get("from_user")
        or message.user_id
    ).strip()
    ats = str(
        message.metadata.get("ats")
        or (message.metadata.get("speaker_id") or "" if message.metadata.get("is_group") else "")
    ).strip()
    if to_wxid:
        binding_store.save_last_target(
            model_name=config.hermes_model_name,
            target={
                "conversation_id": message.conversation_id,
                "user_id": message.user_id,
                "to_wxid": to_wxid,
                "ats": ats,
                "is_group": bool(message.metadata.get("is_group")),
                "updated_from": str(message.metadata.get("updated_from") or "inbound_api"),
            },
        )
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

    await _debounce_enqueue(event, payload)
    return {"ok": True, "buffered": True, "conversation_id": event.conversation_id}
