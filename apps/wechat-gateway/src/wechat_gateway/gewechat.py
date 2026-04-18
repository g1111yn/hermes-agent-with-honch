from __future__ import annotations

import json
import re
import time
import urllib.request
from dataclasses import dataclass
from typing import Any


GEWECHAT_TEXT_MSG_TYPE = 1
GEWECHAT_VOICE_MSG_TYPE = 34


@dataclass(frozen=True)
class GewechatInboundEvent:
    conversation_id: str
    user_id: str
    text: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class GewechatClientConfig:
    api_base: str
    app_id: str
    token: str
    callback_url: str
    auto_register_callback: bool


class GewechatClient:
    def __init__(self, config: GewechatClientConfig):
        self.config = config

    def register_callback(self) -> dict[str, Any]:
        return self._post(
            "/tools/setCallback",
            {
                "appId": self.config.app_id,
                "callbackUrl": self.config.callback_url,
                "token": self.config.token,
            },
        )

    def send_text(self, *, to_wxid: str, content: str, ats: str = "") -> dict[str, Any]:
        return self._post(
            "/message/postText",
            {
                "appId": self.config.app_id,
                "toWxid": to_wxid,
                "content": content,
                "ats": ats,
            },
        )

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.config.api_base}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))


def parse_gewechat_callback(payload: dict[str, Any]) -> GewechatInboundEvent | None:
    data = payload.get("Data") or {}
    add_msg = data.get("AddMsg") or {}
    msg_type = _as_int(add_msg.get("MsgType"))
    if msg_type not in {GEWECHAT_TEXT_MSG_TYPE, GEWECHAT_VOICE_MSG_TYPE}:
        return None

    app_id = str(payload.get("Appid") or payload.get("appId") or "").strip()
    wxid = str(payload.get("Wxid") or payload.get("wxid") or "").strip()

    from_user = str(add_msg.get("FromUserName") or {}).strip()
    to_user = str(add_msg.get("ToUserName") or {}).strip()
    if wxid and from_user == wxid:
        return None

    raw_content = _normalize_text(str(add_msg.get("Content") or ""))
    if not raw_content:
        return None

    is_group = from_user.endswith("@chatroom")
    speaker_id = from_user
    text = raw_content
    ats = ""

    if is_group:
        speaker_id, text = _split_group_speaker(raw_content)
        ats = _extract_mentions(raw_content)

    new_msg_id = str(add_msg.get("NewMsgId") or add_msg.get("MsgId") or "").strip()
    message_id = str(add_msg.get("MsgId") or new_msg_id).strip()
    conversation_id = f"gewechat:{from_user or to_user}"

    metadata: dict[str, Any] = {
        "platform": "wechat",
        "bridge_mode": "gewechat",
        "bridge_name": "gewechat",
        "app_id": app_id,
        "wxid": wxid,
        "from_user": from_user,
        "to_user": to_user,
        "is_group": is_group,
        "message_id": message_id,
        "new_msg_id": new_msg_id,
        "msg_type": msg_type,
    }
    if is_group:
        metadata["group_id"] = from_user
        metadata["speaker_id"] = speaker_id
        if ats:
            metadata["ats"] = ats
    return GewechatInboundEvent(
        conversation_id=conversation_id,
        user_id=speaker_id or from_user,
        text=text,
        metadata=metadata,
    )


def make_dedupe_key(payload: dict[str, Any]) -> str:
    app_id = str(payload.get("Appid") or payload.get("appId") or "").strip()
    add_msg = ((payload.get("Data") or {}).get("AddMsg") or {})
    new_msg_id = str(add_msg.get("NewMsgId") or add_msg.get("MsgId") or "").strip()
    from_user = str(add_msg.get("FromUserName") or "").strip()
    create_time = str(add_msg.get("CreateTime") or int(time.time())).strip()
    return "|".join(part for part in (app_id, from_user, new_msg_id, create_time) if part)


def _normalize_text(text: str) -> str:
    return re.sub(r"\r\n?", "\n", text or "").strip()


def _split_group_speaker(content: str) -> tuple[str, str]:
    if ":\n" in content:
        speaker, text = content.split(":\n", 1)
        return speaker.strip(), text.strip()
    if ":\r\n" in content:
        speaker, text = content.split(":\r\n", 1)
        return speaker.strip(), text.strip()
    return "", content.strip()


def _extract_mentions(content: str) -> str:
    mentions = re.findall(r"@([^\s@]+)", content or "")
    return ",".join(dict.fromkeys(mentions))
def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
