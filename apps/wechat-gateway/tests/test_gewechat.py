from __future__ import annotations

import asyncio
import json
from pathlib import Path

from wechat_gateway import app as app_mod
from wechat_gateway.gewechat import GewechatClient, GewechatClientConfig, make_dedupe_key, parse_gewechat_callback


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

    class FakeBindings:
        def __init__(self):
            self.saved = None

        def save_last_target(self, **kwargs):
            self.saved = kwargs

    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    async def _fake_sleep(_seconds: float) -> None:
        return None

    send_calls = []
    fake_bindings = FakeBindings()

    monkeypatch.setattr(app_mod, "dedupe_store", FakeDedupe())
    monkeypatch.setattr(app_mod, "binding_store", fake_bindings)
    monkeypatch.setattr(
        app_mod.hermes_client,
        "send_message",
        lambda **kwargs: "第一句\n第二句",
    )
    interaction_calls = []
    monkeypatch.setattr(
        app_mod.hermes_client,
        "report_interaction",
        lambda **kwargs: interaction_calls.append(kwargs) or True,
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
    assert fake_bindings.saved["target"]["to_wxid"] == "user_1"
    assert [call["direction"] for call in interaction_calls] == ["inbound", "outbound"]


def test_gewechat_callback_dedupes_duplicate(monkeypatch):
    payload = _sample_payload("hi")

    class FakeDedupe:
        def seen(self, key: str) -> bool:
            return True

    monkeypatch.setattr(app_mod, "dedupe_store", FakeDedupe())

    result = asyncio.run(app_mod.receive_gewechat_callback(payload))

    assert result["ignored"] is True
    assert result["reason"] == "duplicate"


def test_gewechat_client_sends_token_header(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"ret": 200}).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["token"] = request.get_header("X-gewe-token")
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("wechat_gateway.gewechat.urllib.request.urlopen", fake_urlopen)

    client = GewechatClient(
        GewechatClientConfig(
            api_base="http://bridge:2531/v2/api",
            app_id="app-id",
            token="token-123",
            callback_url="http://wechat-gateway:8080/bridges/gewechat/callback",
            auto_register_callback=True,
        )
    )

    result = client.send_text(to_wxid="wxid_1", content="hello")

    assert result["ret"] == 200
    assert captured["url"] == "http://bridge:2531/v2/api/message/postText"
    assert captured["token"] == "token-123"
    assert captured["body"]["appId"] == "app-id"


def test_outbound_message_uses_last_binding(monkeypatch):
    class FakeBindings:
        def get_last_target(self, model_name: str):
            return {"to_wxid": "wxid_last", "ats": ""}

    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    async def _fake_sleep(_seconds: float) -> None:
        return None

    send_calls = []

    monkeypatch.setattr(app_mod, "binding_store", FakeBindings())
    interaction_calls = []
    monkeypatch.setattr(
        app_mod.hermes_client,
        "report_interaction",
        lambda **kwargs: interaction_calls.append(kwargs) or True,
    )
    monkeypatch.setattr(
        app_mod.bridge_client,
        "send_text",
        lambda **kwargs: send_calls.append(kwargs) or {"ret": 200},
    )
    monkeypatch.setattr(app_mod.asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(app_mod.asyncio, "sleep", _fake_sleep)

    request = app_mod.OutboundMessageRequest(text="第一句\n第二句")
    result = asyncio.run(app_mod.send_outbound_message(request, x_gateway_token=app_mod.config.gateway_token))

    assert result["ok"] is True
    assert result["to_wxid"] == "wxid_last"
    assert [call["content"] for call in send_calls] == ["第一句", "第二句"]
    assert interaction_calls[0]["direction"] == "outbound"
