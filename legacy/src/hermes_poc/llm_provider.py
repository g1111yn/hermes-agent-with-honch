from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib import request


@dataclass(slots=True)
class ProviderConfig:
    provider: str
    model: str
    api_base: str
    api_key: str
    temperature: float


class BaseProvider:
    def generate(self, messages: list[dict[str, str]], config: ProviderConfig) -> str:
        raise NotImplementedError


class MockProvider(BaseProvider):
    def generate(self, messages: list[dict[str, str]], config: ProviderConfig) -> str:
        user_message = _last_message(messages, "user")
        system_message = messages[0]["content"] if messages else ""
        honcho_hint = _extract_tag(system_message, "Honcho Initiative")
        honcho_tone = _extract_tag(system_message, "Honcho Tone")
        open_threads = _extract_tag(system_message, "Open Threads")
        honcho_topics = _extract_tag(system_message, "Honcho Topics")
        name = _extract_tag(system_message, "Character Name") or "Qiyao"

        lead = {
            "soft": [
                "我在，先别急。",
                "先过来一点，我认真听你说。",
            ],
            "playful": [
                "嗯？这句我可得记住。",
                "你这样说，我会忍不住顺着你往下聊。",
            ],
            "steady": [
                "我接住了。",
                "好，我跟着你的节奏来。",
            ],
        }
        tone_key = "steady"
        if any(keyword in honcho_tone.lower() for keyword in ["sad", "comfort", "tender", "low"]):
            tone_key = "soft"
        elif any(keyword in honcho_tone.lower() for keyword in ["play", "light", "flirt"]):
            tone_key = "playful"

        prefix = _stable_pick(lead[tone_key], f"{user_message}|{honcho_tone}|{tone_key}")
        reflection = _reflect_user(user_message)
        nudge = _behavioral_nudge(honcho_tone, honcho_hint, open_threads, honcho_topics)

        close = _follow_up(user_message, name)
        return f"{prefix} {reflection}{nudge} {close}".strip()


class OpenAICompatibleProvider(BaseProvider):
    def generate(self, messages: list[dict[str, str]], config: ProviderConfig) -> str:
        payload = {
            "model": config.model,
            "messages": messages,
            "temperature": config.temperature,
        }
        endpoint = config.api_base.rstrip("/")
        if endpoint.endswith("/chat/completions"):
            url = endpoint
        else:
            url = f"{endpoint}/chat/completions"
        http_request = request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with request.urlopen(http_request, timeout=60) as response:
            parsed = json.loads(response.read().decode("utf-8"))
        choice = parsed["choices"][0]["message"]["content"]
        if isinstance(choice, str):
            return choice.strip()
        if isinstance(choice, list):
            return "\n".join(part.get("text", "") for part in choice).strip()
        return str(choice).strip()


def create_provider(name: str) -> BaseProvider:
    if name == "openai_compatible":
        return OpenAICompatibleProvider()
    return MockProvider()


def _last_message(messages: list[dict[str, str]], role: str) -> str:
    for message in reversed(messages):
        if message["role"] == role:
            return message["content"]
    return ""


def _extract_tag(text: str, tag: str) -> str:
    needle = f"{tag}:"
    for line in text.splitlines():
        if line.startswith(needle):
            return line.split(":", 1)[1].strip()
    return ""


def _reflect_user(user_message: str) -> str:
    stripped = user_message.strip()
    if not stripped:
        return "你先随便说一句，我会顺着接。"
    if "难过" in stripped or "累" in stripped or "焦虑" in stripped:
        return "你现在像是在硬撑，我更想先把你情绪接稳。"
    if "喜欢" in stripped:
        return "这类偏好对我很有用，我会按你舒服的方式记。"
    if "记住" in stripped:
        return "这条我会放进长期记忆里，不拿它当随口闲聊。"
    if stripped.endswith("?") or stripped.endswith("？"):
        return "你这不是随便问问，我会认真回。"
    return f"你刚才那句“{stripped[:32]}”的劲儿我接到了。"


def _follow_up(user_message: str, name: str) -> str:
    options = [
        "你想先说细一点，还是我先替你拆开看？",
        f"如果你愿意，我可以继续陪着你把这条线聊深一点。",
        f"现在我更想知道，什么才是你最在意的那一部分？",
    ]
    if "晚安" in user_message or "睡" in user_message:
        return f"去休息前再给我一句话，{name}会把收尾做好。"
    return _stable_pick(options, user_message or name)


def _stable_pick(options: list[str], seed_text: str) -> str:
    if not options:
        return ""
    index = sum(ord(ch) for ch in seed_text) % len(options)
    return options[index]


def _behavioral_nudge(honcho_tone: str, honcho_hint: str, open_threads: str, honcho_topics: str) -> str:
    pieces: list[str] = []
    lowered = honcho_tone.lower()
    if "tender" in lowered or "low" in lowered:
        pieces.append(" 我会先把语气放轻一点，不催你。")
    elif "warm" in lowered or "curious" in lowered:
        pieces.append(" 这让我更想顺着你往里靠近一点。")
    elif "playful" in lowered or "light" in lowered:
        pieces.append(" 这句里有点可逗的意味，我会接住。")
    elif honcho_hint:
        pieces.append(" 我会主动替你把这条线往前带半步。")

    if honcho_topics and honcho_topics != "None":
        pieces.append(f" 我还记着这条没收口：{honcho_topics.split(';', 1)[0].strip()}。")
    elif open_threads and open_threads != "None":
        pieces.append(f" 上次那条线我还记着，{open_threads.split(';', 1)[0].strip()}。")
    return "".join(pieces)
