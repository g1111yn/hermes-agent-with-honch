from __future__ import annotations

import asyncio

from wechat_gateway import app as app_mod
from wechat_gateway.gewechat import make_dedupe_key, parse_gewechat_callback


def _sample_payload(content: str = "hi") -> dict:
    return {
        "Appid": "wx-app-1",
        "Wxid": "wxid_bot",
        "Data": {
            "AddMsg": {
                "MsgId": "123",
                "NewMsgId": "456",
                "MsgType": 1,
                "FromUserName": "user_1",
                "ToUserName": "wxid_bot",
                "Content": content,
                "CreateTime": 1710000000,
            }
        },
    }


def test_parse_gewechat_text_message():
    event = parse_gewechat_callback(_sample_payload("你好"))

    assert event is not None
    assert event.conversation_id == "gewechat:user_1"
    assert event.user_id == "user_1"
    assert event.text == "你好"
    assert event.metadata["message_id"] == "123"
    assert event.metadata["new_msg_id"] == "456"


def test_parse_gewechat_group_message_extracts_speaker():
    payload = _sample_payload("wxid_member:\n在吗")
    payload["Data"]["AddMsg"]["FromUserName"] = "123@chatroom"

    event = parse_gewechat_callback(payload)

    assert event is not None
    assert event.user_id == "wxid_member"
    assert event.text == "在吗"
    assert event.metadata["group_id"] == "123@chatroom"
    assert event.metadata["speaker_id"] == "wxid_member"


def test_make_dedupe_key_uses_app_and_new_msg_id():
    key = make_dedupe_key(_sample_payload("你好"))
    assert key == "wx-app-1|user_1|456|1710000000"


def test_gewechat_callback_sends_segmented_replies(monkeypatch):
    payload = _sample_payload("hi")

    class FakeDedupe:
        def seen(self, key: str) -> bool:
            return False

    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    async def _fake_sleep(_seconds: float) -> None:
        return None

    send_calls = []

    monkeypatch.setattr(app_mod, "dedupe_store", FakeDedupe())
    monkeypatch.setattr(
        app_mod.hermes_client,
        "send_message",
        lambda **kwargs: "第一句\n第二句",
    )
    monkeypatch.setattr(
        app_mod.bridge_client,
        "send_text",
        lambda **kwargs: send_calls.append(kwargs) or {"ret": 200, "data": {"toWxid": kwargs["to_wxid"]}},
    )
    monkeypatch.setattr(app_mod.asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(app_mod.asyncio, "sleep", _fake_sleep)

    result = asyncio.run(app_mod.receive_gewechat_callback(payload))

    assert result["ok"] is True
    assert result["sent_count"] == 2
    assert [call["content"] for call in send_calls] == ["第一句", "第二句"]
    assert all(call["to_wxid"] == "user_1" for call in send_calls)


def test_gewechat_callback_dedupes_duplicate(monkeypatch):
    payload = _sample_payload("hi")

    class FakeDedupe:
        def seen(self, key: str) -> bool:
            return True

    monkeypatch.setattr(app_mod, "dedupe_store", FakeDedupe())

    result = asyncio.run(app_mod.receive_gewechat_callback(payload))

    assert result["ignored"] is True
    assert result["reason"] == "duplicate"
