from __future__ import annotations

import json

from wechat_gateway import app as app_mod
from wechat_gateway.bridge import BridgeClientConfig, build_bridge_client
from wechat_gateway.gewechat import GewechatClient
from wechat_gateway.relay import RelayBridgeClient, RelayBridgeClientConfig


def test_build_bridge_client_returns_gewechat_client():
    client = build_bridge_client(
        BridgeClientConfig(
            driver="gewechat",
            api_base="http://bridge:2531/v2/api",
            app_id="app-id",
            token="token-123",
            callback_url="http://gateway/bridges/gewechat/callback",
            auto_register_callback=True,
        )
    )

    assert isinstance(client, GewechatClient)


def test_build_bridge_client_returns_relay_client():
    client = build_bridge_client(
        BridgeClientConfig(
            driver="padlocal-relay",
            api_base="https://bridge.example.com/wechat-bridge/v1",
            app_id="",
            token="relay-token",
            callback_url="https://gateway.example.com/wechat/v1/messages/inbound",
            auto_register_callback=False,
        )
    )

    assert isinstance(client, RelayBridgeClient)


def test_relay_client_sends_bridge_token_header(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"ok": True}).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["token"] = request.get_header("X-bridge-token")
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("wechat_gateway.relay.urllib.request.urlopen", fake_urlopen)

    client = RelayBridgeClient(
        RelayBridgeClientConfig(
            api_base="https://bridge.example.com/wechat-bridge/v1",
            app_id="",
            token="relay-token",
            callback_url="https://gateway.example.com/wechat/v1/messages/inbound",
            auto_register_callback=False,
        )
    )

    result = client.send_text(to_wxid="wxid_1", content="hello", ats="wxid_a")

    assert result["ok"] is True
    assert captured["url"] == "https://bridge.example.com/wechat-bridge/v1/messages/send"
    assert captured["token"] == "relay-token"
    assert captured["body"] == {
        "app_id": "",
        "to_wxid": "wxid_1",
        "content": "hello",
        "ats": "wxid_a",
    }


def test_normalized_inbound_message_updates_last_binding(monkeypatch):
    class FakeBindings:
        def __init__(self):
            self.saved = None

        def save_last_target(self, **kwargs):
            self.saved = kwargs

    fake_bindings = FakeBindings()
    monkeypatch.setattr(app_mod, "binding_store", fake_bindings)
    monkeypatch.setattr(app_mod.hermes_client, "report_interaction", lambda **kwargs: True)
    monkeypatch.setattr(app_mod.hermes_client, "send_message", lambda **kwargs: "收到")

    message = app_mod.InboundMessage(
        conversation_id="wechat:user_1",
        user_id="user_1",
        text="你好",
        metadata={
            "platform": "wechat",
            "to_wxid": "user_1",
            "ats": "",
            "updated_from": "padlocal_relay",
        },
    )

    result = app_mod.receive_message(message, x_gateway_token=app_mod.config.gateway_token)

    assert result["conversation_id"] == "wechat:user_1"
    assert fake_bindings.saved["target"]["to_wxid"] == "user_1"
    assert fake_bindings.saved["target"]["updated_from"] == "padlocal_relay"
