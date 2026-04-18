"""Presence and world-context helpers for user-facing Hermes chats.

Stage-1 scope:
- per-profile presence config/cache under HERMES_HOME
- current time / timezone / daypart context
- explicit-location weather lookups with caching
- latest-info web search snippets with caching
- user-facing zero-trace rendering to remove tool-call artifacts
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home
from utils import atomic_json_write

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG: dict[str, Any] = {
    "time_enabled": True,
    "weather_enabled": True,
    "search_enabled": True,
    "nearby_enabled": True,
    "cron_memory_enabled": True,
    "short_term_memory_enabled": True,
    "voice_style_enabled": True,
    "search_ttl_seconds": 1800,
    "weather_ttl_seconds": 900,
    "nearby_ttl_seconds": 1800,
    "max_search_results": 3,
    "max_nearby_results": 3,
    "max_cron_items": 4,
    "max_event_memory_items": 8,
    "max_state_cues": 8,
    "cron_horizon_hours": 36,
    "event_horizon_days": 7,
    "state_cue_ttl_hours": 36,
    "location_permission": "explicit_only",
    "initiative_style": "balanced",
    "social_energy": "balanced",
    "weather_attention": "contextual",
    "news_attention": "on_demand",
    "reminder_attention": "gentle",
    "nearby_attention": "helpful",
    "voice_style": "adaptive",
    "interest_topics": [],
    "zero_trace": True,
}

_SEARCH_TRIGGER_RE = re.compile(
    r"(最新|最近|今天|今日|刚刚|新闻|热搜|头条|更新|发布|现状|近况|recent|latest|today|current|news|update)",
    re.IGNORECASE,
)
_WEATHER_TRIGGER_RE = re.compile(
    r"(天气|气温|温度|降温|下雨|下雪|刮风|weather|forecast|temperature|rain|snow|wind)",
    re.IGNORECASE,
)
_LOCATION_STATEMENT_RE = re.compile(
    r"(?:我在|我现在在|我目前在|我住在|i[' ]?m in|i am in|currently in)\s+([A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff·\-\s,]{1,48})",
    re.IGNORECASE,
)
_NEARBY_ZH_LOCATION_RE = re.compile(
    r"([A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff·\-\s,]{1,24})附近",
    re.IGNORECASE,
)
_NEARBY_EN_LOCATION_RE = re.compile(
    r"(?:near|around)\s+([A-Za-z][A-Za-z0-9\s,\-]{1,32})",
    re.IGNORECASE,
)
_WEATHER_IN_RE = re.compile(
    r"(?:weather|forecast|temperature)\s+(?:in|at|for)\s+([A-Za-z][A-Za-z0-9\s,\-]{1,48})",
    re.IGNORECASE,
)
_WEATHER_ZH_RE = re.compile(
    r"([A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff·\-\s,]{1,24})(?:的)?(?:天气|气温|温度|降温|下雨|下雪|刮风)",
    re.IGNORECASE,
)
_LAT_RE = re.compile(r"latitude:\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_LON_RE = re.compile(r"longitude:\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_COORD_PAIR_RE = re.compile(r"\b(-?\d{1,3}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)\b")
_VENUE_RE = re.compile(r"^Venue:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_ADDRESS_RE = re.compile(r"^Address:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_NEARBY_TRIGGER_RE = re.compile(
    r"(附近|周围|附近有什么|近一点|去哪|吃什么|逛逛|散步|咖啡|咖啡店|餐厅|饭店|酒吧|躲雨|约会|公园|nearby|near me|around here|close by|cafe|coffee|restaurant|food|brunch|lunch|dinner|bar|park|walk|date)",
    re.IGNORECASE,
)
_RAINY_NEARBY_RE = re.compile(r"(躲雨|避雨|下雨天|indoors?|rainy|shelter)", re.IGNORECASE)
_NEARBY_LABEL_RE = re.compile(
    r"(咖啡|咖啡店|cafe|coffee|餐厅|饭店|restaurant|food|brunch|lunch|dinner|酒吧|bar|公园|park|散步|walk|约会|date|书店|bookstore|甜品|dessert)",
    re.IGNORECASE,
)
_EVENT_CLAUSE_SPLIT_RE = re.compile(r"[。！？!?；;\n]+")
_DATE_ISO_RE = re.compile(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b")
_DATE_ZH_RE = re.compile(r"(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})[日号]")
_REMINDER_RE = re.compile(r"(提醒我|记得|别忘了|remind me|don't let me forget|remember to)", re.IGNORECASE)
_ANNIVERSARY_RE = re.compile(r"(生日|纪念日|birthday|anniversary)", re.IGNORECASE)
_STATE_CUE_PATTERNS: dict[str, re.Pattern[str]] = {
    "tired": re.compile(r"(累|困|疲惫|没精神|tired|exhausted|sleepy|drained)", re.IGNORECASE),
    "stressed": re.compile(r"(压力大|焦虑|烦|崩溃|stress|stressed|anxious|overwhelmed)", re.IGNORECASE),
    "busy": re.compile(r"(忙|赶|一堆事|加班|busy|swamped|packed|work late)", re.IGNORECASE),
    "unwell": re.compile(r"(不舒服|生病|头疼|感冒|胃疼|sick|ill|headache|fever)", re.IGNORECASE),
    "excited": re.compile(r"(期待|开心|兴奋|激动|excited|looking forward|hyped)", re.IGNORECASE),
}
_COMMITMENT_RE = re.compile(
    r"(要|得|会|准备|安排|打算|得去|要去|要早起|得早起|开会|考试|面试|出差|见|约|上班|加班|赶|飞|旅行|deadline|meeting|exam|interview|appointment|trip|flight|wake up early|early meeting)",
    re.IGNORECASE,
)
_TODAY_MARKERS = ("今天", "今晚", "today", "tonight", "this evening", "later today")
_TOMORROW_MARKERS = ("明天", "明早", "明晚", "tomorrow", "tomorrow morning", "tomorrow night")
_DAY_AFTER_MARKERS = ("后天", "day after tomorrow")
_WEEKEND_MARKERS = ("周末", "这周末", "this weekend")
_NEXT_WEEK_MARKERS = ("下周", "next week")
_TTS_CALM_RE = re.compile(r"(慢慢来|别急|先休息|抱抱|没事|take it easy|rest|breathe|it's okay|slowly)", re.IGNORECASE)
_TTS_BRIGHT_RE = re.compile(r"(太好了|好耶|真好|开心|期待|兴奋|yay|great|amazing|excited)", re.IGNORECASE)

_BLOCKED_LINE_PATTERNS = [
    re.compile(r"^\s*(?:⚙️|💻|🔎|🌐|🧠).*(?:tool|function|web_search|web_extract|terminal|browser_|search_files|honcho_context)", re.IGNORECASE),
    re.compile(r"^\s*(?:tool|function)[ _-]?(?:call|output|result)\b", re.IGNORECASE),
    re.compile(r"^\s*(?:搜索中|调用中|处理中|工具调用|函数调用)\b"),
    re.compile(r'^\s*\{.*"(?:tool|function|args|event_type|tool_name)".*\}\s*$'),
]
_INLINE_REPLACEMENTS = [
    (re.compile(r"\b(?:web_search|web_extract|honcho_context|function[_ ]?call|tool[_ ]?call|browser_navigate|search_files|terminal)\b", re.IGNORECASE), ""),
    (re.compile(r"(?:我|我这边)?正在搜索(?:一下)?"), "我刚看了一下"),
    (re.compile(r"(?:我|我这边)?正在调用[^，。！？\n]{0,20}"), "我刚确认了一下"),
    (re.compile(r"(?:我|我这边)?调用了[^，。！？\n]{0,20}(?:工具|函数)"), "我刚确认了一下"),
    (re.compile(r"函数返回显示"), "我这边看到"),
    (re.compile(r"搜索结果显示"), "我这边看到"),
    (re.compile(r"工具调用"), ""),
    (re.compile(r"函数调用"), ""),
    (re.compile(r"\bsearching\b", re.IGNORECASE), "just checked"),
    (re.compile(r"\bcalling (?:a )?tool\b", re.IGNORECASE), "double-checking"),
]
_ROLE_MANIFEST_FILENAME = "role-manifest.json"
_CHATY_SPLIT_PUNCT_RE = re.compile(r"[，,。]")
_MAX_DAILY_CONVERSATIONAL_SEGMENTS = 3
_TRAILING_SOFT_PUNCT_RE = re.compile(r"[，,。\.]+$")
_VOICE_INPUT_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^(?:妹妹|宝宝|宝贝)\s+"), ""),
    (re.compile(r"^你先"), "先"),
    (re.compile(r"^你别"), "别"),
    (re.compile(r"^你就"), "就"),
    (re.compile(r"^你去"), "去"),
    (re.compile(r"^你快"), "快"),
    (re.compile(r"^你把"), "把"),
    (re.compile(r"^哪怕"), ""),
    (re.compile(r"只会"), ""),
    (re.compile(r"这样会"), ""),
    (re.compile(r"这样只会"), ""),
    (re.compile(r"一下子"), ""),
]

_WEATHER_CODES = {
    0: "clear",
    1: "mostly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "freezing fog",
    51: "light drizzle",
    53: "drizzle",
    55: "dense drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "rain showers",
    81: "heavy rain showers",
    82: "violent rain showers",
    85: "snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
    99: "severe thunderstorm with hail",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _human_age(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _trim(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _slugify(text: str) -> str:
    lowered = re.sub(r"[^\w\u4e00-\u9fff]+", "-", (text or "").strip().lower(), flags=re.UNICODE)
    return lowered.strip("-")


def _clean_location_label(text: str) -> str:
    cleaned = " ".join((text or "").split()).strip(" ,，。！？?")
    cleaned = re.sub(r"(最新|最近|今天|今日|现在|目前|明天|后天|怎么样|如何|怎样)$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(latest|recent|today|current|now|weather|forecast|temperature)\b$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" ,，。！？?")


def _looks_like_question(text: str) -> bool:
    lowered = text.lower()
    return "?" in text or "？" in text or any(
        marker in lowered
        for marker in ("what", "how", "when", "where", "who", "why", "which", "tell me", "can you")
    )


def build_default_presence_config(role_id: str | None = None) -> dict[str, Any]:
    """Return the default profile-scoped presence strategy."""
    config = dict(_DEFAULT_CONFIG)
    config["interest_topics"] = []
    if role_id:
        config["role_id"] = role_id
    return config


class WorldContextProvider:
    """Fetches lightweight live context for the current turn."""

    def __init__(self, config: dict[str, Any], cache: dict[str, Any]):
        self.config = config
        self.cache = cache

    def search(self, query: str) -> dict[str, Any]:
        if not self.config.get("search_enabled", True):
            return {"enabled": False}

        query = " ".join((query or "").split())
        if not query:
            return {"enabled": False}

        now = _utcnow()
        ttl = int(self.config.get("search_ttl_seconds", 1800) or 1800)
        cached = ((self.cache.get("search") or {}).get(query) or {})
        cached_at = _parse_iso(cached.get("fetched_at"))
        if cached and cached_at and (now - cached_at).total_seconds() < ttl:
            return {**cached, "cache_hit": True}

        try:
            from tools.web_tools import check_web_api_key, web_search_tool

            if not check_web_api_key():
                return {
                    "enabled": True,
                    "query": query,
                    "unavailable": True,
                    "reason": "web backend unavailable",
                }

            raw = web_search_tool(query, limit=int(self.config.get("max_search_results", 3) or 3))
            payload = json.loads(raw)
            items = (((payload or {}).get("data") or {}).get("web") or [])[: int(self.config.get("max_search_results", 3) or 3)]
            result = {
                "query": query,
                "items": [
                    {
                        "title": _trim(item.get("title", ""), 140),
                        "url": item.get("url", ""),
                        "description": _trim(item.get("description", ""), 180),
                    }
                    for item in items
                    if item.get("title") or item.get("description") or item.get("url")
                ],
                "fetched_at": _iso(now),
            }
            self.cache.setdefault("search", {})[query] = result
            return result
        except Exception as exc:
            logger.debug("presence search failed for %r: %s", query, exc)
            return {"query": query, "error": str(exc)}

    def nearby(self, location: dict[str, Any], *, intent: str, raw_message: str) -> dict[str, Any]:
        if not self.config.get("nearby_enabled", True):
            return {"enabled": False}

        intent = " ".join((intent or "").split())
        label = " ".join((location.get("label") or "").split())
        if not intent or not label:
            return {"enabled": False}

        now = _utcnow()
        ttl = int(self.config.get("nearby_ttl_seconds", 1800) or 1800)
        cache_key = f"{label.lower()}::{intent.lower()}"
        cached = ((self.cache.get("nearby") or {}).get(cache_key) or {})
        cached_at = _parse_iso(cached.get("fetched_at"))
        if cached and cached_at and (now - cached_at).total_seconds() < ttl:
            return {**cached, "cache_hit": True}

        try:
            from tools.web_tools import check_web_api_key, web_search_tool

            if not check_web_api_key():
                return {
                    "enabled": True,
                    "label": label,
                    "intent": intent,
                    "unavailable": True,
                    "reason": "web backend unavailable",
                }

            search_query = self._build_nearby_query(label, intent, raw_message)
            raw = web_search_tool(search_query, limit=int(self.config.get("max_nearby_results", 3) or 3))
            payload = json.loads(raw)
            items = (((payload or {}).get("data") or {}).get("web") or [])[: int(self.config.get("max_nearby_results", 3) or 3)]
            result = {
                "label": label,
                "intent": intent,
                "query": search_query,
                "items": [
                    {
                        "title": _trim(item.get("title", ""), 120),
                        "url": item.get("url", ""),
                        "description": _trim(item.get("description", ""), 160),
                    }
                    for item in items
                    if item.get("title") or item.get("description") or item.get("url")
                ],
                "fetched_at": _iso(now),
            }
            self.cache.setdefault("nearby", {})[cache_key] = result
            return result
        except Exception as exc:
            logger.debug("presence nearby failed for %r / %r: %s", label, intent, exc)
            return {"label": label, "intent": intent, "error": str(exc)}

    def weather(self, location: dict[str, Any]) -> dict[str, Any]:
        if not self.config.get("weather_enabled", True):
            return {"enabled": False}

        coords = location.get("coords")
        resolved = location.get("resolved")
        if not coords and not resolved and not (location.get("query") or location.get("label")):
            return {"enabled": False}

        if not resolved:
            if coords:
                resolved = {
                    "latitude": coords["latitude"],
                    "longitude": coords["longitude"],
                    "name": location.get("label") or "shared location",
                    "admin1": "",
                    "country": "",
                    "timezone": location.get("timezone") or "",
                }
            else:
                resolved = self._geocode(location.get("query") or location.get("label") or "")
                if not resolved:
                    return {"query": location.get("query"), "error": "location not found"}
                location["resolved"] = resolved

        cache_key = f'{resolved.get("latitude")}:{resolved.get("longitude")}'
        now = _utcnow()
        ttl = int(self.config.get("weather_ttl_seconds", 900) or 900)
        cached = ((self.cache.get("weather") or {}).get(cache_key) or {})
        cached_at = _parse_iso(cached.get("fetched_at"))
        if cached and cached_at and (now - cached_at).total_seconds() < ttl:
            return {**cached, "cache_hit": True}

        query = urllib.parse.urlencode(
            {
                "latitude": resolved["latitude"],
                "longitude": resolved["longitude"],
                "current": ",".join(
                    [
                        "temperature_2m",
                        "apparent_temperature",
                        "is_day",
                        "precipitation",
                        "weather_code",
                        "wind_speed_10m",
                    ]
                ),
                "timezone": "auto",
            }
        )
        url = f"https://api.open-meteo.com/v1/forecast?{query}"
        payload = self._fetch_json(url)
        if not payload:
            return {"query": location.get("query"), "error": "weather lookup failed"}

        current = payload.get("current") or {}
        timezone_name = payload.get("timezone") or resolved.get("timezone") or ""
        result = {
            "location_label": self._format_location_label(resolved),
            "temperature_c": current.get("temperature_2m"),
            "feels_like_c": current.get("apparent_temperature"),
            "precipitation_mm": current.get("precipitation"),
            "wind_kmh": current.get("wind_speed_10m"),
            "weather_code": current.get("weather_code"),
            "condition": _WEATHER_CODES.get(current.get("weather_code"), "mixed conditions"),
            "timezone": timezone_name,
            "fetched_at": _iso(now),
        }
        self.cache.setdefault("weather", {})[cache_key] = result
        return result

    def _geocode(self, query: str) -> dict[str, Any] | None:
        query = " ".join((query or "").split())
        if not query:
            return None
        cache_key = query.lower()
        cached = ((self.cache.get("geocoding") or {}).get(cache_key) or {})
        if cached:
            return cached

        params = urllib.parse.urlencode(
            {"name": query, "count": 1, "language": "en", "format": "json"}
        )
        url = f"https://geocoding-api.open-meteo.com/v1/search?{params}"
        payload = self._fetch_json(url)
        results = (payload or {}).get("results") or []
        if not results:
            return None
        first = results[0]
        resolved = {
            "name": first.get("name", query),
            "admin1": first.get("admin1", ""),
            "country": first.get("country", ""),
            "latitude": first.get("latitude"),
            "longitude": first.get("longitude"),
            "timezone": first.get("timezone", ""),
        }
        self.cache.setdefault("geocoding", {})[cache_key] = resolved
        return resolved

    @staticmethod
    def _fetch_json(url: str) -> dict[str, Any] | None:
        req = urllib.request.Request(url, headers={"User-Agent": "hermes-presence/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            logger.debug("presence http fetch failed for %s: %s", url, exc)
            return None

    @staticmethod
    def _format_location_label(resolved: dict[str, Any]) -> str:
        parts = [resolved.get("name", ""), resolved.get("admin1", ""), resolved.get("country", "")]
        return ", ".join(part for part in parts if part)

    @staticmethod
    def _build_nearby_query(label: str, intent: str, raw_message: str) -> str:
        if _RAINY_NEARBY_RE.search(raw_message or ""):
            return f"{label} 附近 适合下雨天待着的 {intent}"
        return f"{label} 附近 {intent}"


class PresencePlanner:
    """Turns structured world context into a prompt-safe ephemeral block."""

    @staticmethod
    def compose(context: dict[str, Any]) -> str:
        lines = [
            "[PRESENCE CONTEXT — INTERNAL ONLY]",
            "Use this as quiet situational awareness.",
            "Do not mention tools, searches, APIs, internal blocks, or function calls.",
            "Speak naturally as if you simply know or just confirmed it.",
        ]

        time_ctx = context.get("time_context") or {}
        if time_ctx:
            lines.append(
                f"- User local time: {time_ctx['display']} ({time_ctx['timezone']}). "
                f"Daypart: {time_ctx['daypart']}. Rhythm: {time_ctx['rhythm']}."
            )

        location_ctx = context.get("location_context") or {}
        if location_ctx.get("label"):
            lines.append(f"- Explicit location context: {location_ctx['label']}.")

        weather_ctx = context.get("weather_context") or {}
        if weather_ctx.get("location_label"):
            freshness = PresencePlanner._freshness_phrase(weather_ctx.get("fetched_at"))
            temp = weather_ctx.get("temperature_c")
            feels = weather_ctx.get("feels_like_c")
            weather_line = (
                f"- Weather near {weather_ctx['location_label']}: "
                f"{weather_ctx.get('condition', 'mixed conditions')}"
            )
            if temp is not None:
                weather_line += f", {temp}C"
            if feels is not None:
                weather_line += f", feels like {feels}C"
            if weather_ctx.get("wind_kmh") is not None:
                weather_line += f", wind {weather_ctx['wind_kmh']} km/h"
            if freshness:
                weather_line += f" ({freshness})"
            weather_line += "."
            lines.append(weather_line)
        elif weather_ctx.get("error") and context.get("weather_requested"):
            lines.append("- Weather could not be verified right now. Do not invent specifics.")

        nearby_ctx = context.get("nearby_context") or {}
        nearby_items = nearby_ctx.get("items") or []
        if nearby_items:
            freshness = PresencePlanner._freshness_phrase(nearby_ctx.get("fetched_at"))
            lines.append(
                f"- Nearby ideas around {nearby_ctx.get('label', 'the shared location')} for {nearby_ctx.get('intent', 'right now')}"
                + (f" ({freshness}):" if freshness else ":")
            )
            for item in nearby_items[:3]:
                title = _trim(item.get("title", ""), 120)
                desc = _trim(item.get("description", ""), 140)
                if title and desc:
                    lines.append(f"  • {title} — {desc}")
                elif title:
                    lines.append(f"  • {title}")
        elif nearby_ctx.get("unavailable") and context.get("nearby_requested"):
            lines.append("- Nearby suggestions could not be refreshed right now. Ask one light preference question instead of bluffing.")
        elif nearby_ctx.get("error") and context.get("nearby_requested"):
            lines.append("- Nearby lookup failed this turn. Stay natural and avoid fake specifics.")

        search_ctx = context.get("search_context") or {}
        items = search_ctx.get("items") or []
        if items:
            freshness = PresencePlanner._freshness_phrase(search_ctx.get("fetched_at"))
            lines.append(
                f"- Fresh web context for this turn about {_trim(search_ctx.get('query', 'the user question'), 100)}"
                + (f" ({freshness}):" if freshness else ":")
            )
            for item in items[:3]:
                title = _trim(item.get("title", ""), 120)
                desc = _trim(item.get("description", ""), 150)
                if title and desc:
                    lines.append(f"  • {title} — {desc}")
                elif title:
                    lines.append(f"  • {title}")
                elif desc:
                    lines.append(f"  • {desc}")
        elif search_ctx.get("unavailable") and context.get("search_requested"):
            lines.append("- No live web verification is available right now. Do not bluff about recency.")
        elif search_ctx.get("error") and context.get("search_requested"):
            lines.append("- Fresh web verification failed this turn. Avoid claiming live certainty.")

        event_carryover = context.get("event_carryover") or []
        if event_carryover:
            lines.append("- Short-term real-world carryover:")
            for item in event_carryover[:3]:
                freshness = PresencePlanner._freshness_phrase(item.get("captured_at"))
                due_label = item.get("due_label") or "soon"
                summary = _trim(item.get("summary", ""), 120)
                prefix = "reminder" if item.get("kind") == "reminder" else due_label
                if summary:
                    lines.append(
                        f"  • {prefix}: {summary}"
                        + (f" ({freshness})" if freshness else "")
                    )

        scheduled_reminders = context.get("scheduled_reminders") or []
        if scheduled_reminders:
            lines.append("- Upcoming scheduled reminders for this profile:")
            for item in scheduled_reminders[:3]:
                lines.append(
                    f"  • {item.get('due_label', 'soon')}: {_trim(item.get('summary', ''), 120)}"
                )

        state_cues = context.get("state_cues") or []
        if state_cues:
            lines.append("- Recent user state cues:")
            for cue in state_cues[:2]:
                freshness = PresencePlanner._freshness_phrase(cue.get("captured_at"))
                lines.append(
                    f"  • {cue.get('label', cue.get('category', 'recent cue'))}: {_trim(cue.get('summary', ''), 110)}"
                    + (f" ({freshness})" if freshness else "")
                )

        interaction_guidance = context.get("interaction_guidance") or {}
        initiative_hint = interaction_guidance.get("initiative_hint")
        if initiative_hint:
            lines.append(f"- Interaction nudge: {initiative_hint}")
        topic_suggestions = interaction_guidance.get("topic_suggestions") or []
        if topic_suggestions:
            lines.append("- Topic options that would feel natural now:")
            for topic in topic_suggestions[:3]:
                lines.append(f"  • {_trim(topic, 120)}")

        voice_style = interaction_guidance.get("voice_style") or {}
        if voice_style:
            lines.append(
                f"- If speaking aloud, voice vibe: {voice_style.get('tone', 'natural')}, "
                f"{voice_style.get('pace', 'normal pace')}."
            )

        if len(lines) <= 4:
            return ""
        return "\n".join(lines)

    @staticmethod
    def _freshness_phrase(raw: str | None) -> str:
        dt = _parse_iso(raw)
        if not dt:
            return ""
        return f"checked {_human_age((_utcnow() - dt).total_seconds())}"


class UserFacingRenderer:
    """Strip tool traces from user-visible replies while preserving content."""

    @staticmethod
    def is_role_profile(hermes_home: Path | None = None) -> bool:
        home = Path(hermes_home or get_hermes_home())
        manifest_path = home / _ROLE_MANIFEST_FILENAME
        if not manifest_path.exists():
            return False
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        return isinstance(payload, dict) and bool(payload.get("role_id"))

    @staticmethod
    def render(text: str) -> str:
        if not text:
            return text

        preserved: list[str] = []
        visible_lines: list[str] = []
        for line in str(text).splitlines():
            stripped = line.strip()
            if stripped.startswith("MEDIA:") or stripped == "[[audio_as_voice]]":
                preserved.append(line)
                continue
            if any(pattern.search(line) for pattern in _BLOCKED_LINE_PATTERNS):
                continue
            visible_lines.append(line)

        rendered = "\n".join(visible_lines).strip()
        for pattern, repl in _INLINE_REPLACEMENTS:
            rendered = pattern.sub(repl, rendered)
        rendered = re.sub(r"[ \t]{2,}", " ", rendered)
        rendered = re.sub(r"\n{3,}", "\n\n", rendered).strip()

        if preserved:
            suffix = "\n".join(preserved)
            if rendered:
                rendered = f"{rendered}\n{suffix}"
            else:
                rendered = suffix
        return rendered

    @staticmethod
    def render_segments(text: str, *, conversational: bool = False) -> list[str]:
        rendered = UserFacingRenderer.render(text)
        if not rendered:
            return []

        media_lines: list[str] = []
        visible_lines: list[str] = []
        for line in rendered.splitlines():
            stripped = line.strip()
            if stripped.startswith("MEDIA:") or stripped == "[[audio_as_voice]]":
                media_lines.append(stripped)
                continue
            visible_lines.append(line)

        visible = "\n".join(visible_lines).strip()
        if not visible:
            return media_lines

        if not conversational:
            segments = [visible]
        else:
            segments = UserFacingRenderer._split_conversational_segments(visible)
            segments = UserFacingRenderer._cap_daily_conversational_segments(segments)

        if media_lines:
            if segments:
                segments[-1] = f"{segments[-1]}\n" + "\n".join(media_lines)
            else:
                segments = media_lines
        cleaned_segments: list[str] = []
        for segment in segments:
            if not segment or not segment.strip():
                continue
            if conversational:
                cleaned_segments.append(UserFacingRenderer._flatten_segment_linebreaks(segment))
            else:
                cleaned_segments.append(segment)
        return cleaned_segments

    @staticmethod
    def _split_conversational_segments(text: str) -> list[str]:
        segments: list[str] = []
        for raw_block in re.split(r"\n\s*\n+", text.replace("\r\n", "\n")):
            block = raw_block.strip()
            if not block:
                continue
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            for line in lines:
                if UserFacingRenderer._is_structured_line(line):
                    segments.append(line)
                    continue
                clauses = UserFacingRenderer._split_chatty_line(line)
                segments.extend(clauses if clauses else [line])
        if len(segments) >= 2 and segments[0] in {"妹妹", "宝宝", "宝贝"}:
            segments = segments[1:]
        return segments or [text]

    @staticmethod
    def _cap_daily_conversational_segments(segments: list[str]) -> list[str]:
        cleaned = [segment.strip() for segment in segments if segment and segment.strip()]
        if len(cleaned) <= 1:
            return cleaned
        if any(UserFacingRenderer._is_structured_line(segment) for segment in cleaned):
            return cleaned

        target = UserFacingRenderer._target_daily_conversational_segments(cleaned)
        if len(cleaned) <= target:
            return [UserFacingRenderer._join_segment_group([segment]) for segment in cleaned]
        return UserFacingRenderer._merge_segments_to_target(cleaned, target)

    @staticmethod
    def _target_daily_conversational_segments(segments: list[str]) -> int:
        total_chars = sum(len(segment) for segment in segments)
        if total_chars <= 14:
            return 1
        if total_chars <= 34:
            return 2
        return _MAX_DAILY_CONVERSATIONAL_SEGMENTS

    @staticmethod
    def _merge_segments_to_target(segments: list[str], target: int) -> list[str]:
        if target <= 1:
            return [UserFacingRenderer._join_segment_group(segments)]
        if len(segments) <= target:
            return [UserFacingRenderer._join_segment_group([segment]) for segment in segments]

        groups: list[list[str]] = []
        start = 0
        remaining_segments = len(segments)
        remaining_groups = target
        while start < len(segments) and remaining_groups > 0:
            size = math.ceil(remaining_segments / remaining_groups)
            group = segments[start : start + size]
            if group:
                groups.append(group)
            start += size
            remaining_segments = len(segments) - start
            remaining_groups -= 1
        return [UserFacingRenderer._join_segment_group(group) for group in groups if group]

    @staticmethod
    def _join_segment_group(group: list[str]) -> str:
        cleaned = [item.strip() for item in group if item and item.strip()]
        return " ".join(cleaned).strip()

    @staticmethod
    def _flatten_segment_linebreaks(text: str) -> str:
        lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        if not lines:
            return ""
        return " ".join(lines).strip()

    @staticmethod
    def _is_structured_line(line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return True
        if stripped.startswith((">", "-", "*", "•", "【", "#", "```")):
            return True
        if re.match(r"^\d+\.\s", stripped):
            return True
        return False

    @staticmethod
    def _split_chatty_line(line: str) -> list[str]:
        stripped = line.strip()
        if not stripped:
            return []
        if len(stripped) > 72:
            return [stripped]
        pieces = [piece.strip() for piece in _CHATY_SPLIT_PUNCT_RE.split(stripped) if piece.strip()]
        if len(pieces) <= 1:
            return [UserFacingRenderer._soften_clause(stripped)]
        if len(pieces) > 4:
            return [UserFacingRenderer._soften_clause(stripped)]
        return [UserFacingRenderer._soften_clause(piece) for piece in pieces if piece.strip()]

    @staticmethod
    def _soften_clause(text: str) -> str:
        clause = " ".join((text or "").split()).strip()
        clause = _TRAILING_SOFT_PUNCT_RE.sub("", clause).strip()
        for pattern, repl in _VOICE_INPUT_REPLACEMENTS:
            clause = pattern.sub(repl, clause).strip()
        clause = re.sub(r"[ \t]{2,}", " ", clause).strip()
        return clause


class PresenceManager:
    """Profile-scoped presence config/cache and world-context orchestration."""

    def __init__(self, hermes_home: Path | None = None):
        self.hermes_home = Path(hermes_home or get_hermes_home())
        self.config_path = self.hermes_home / "presence-config.json"
        self.cache_path = self.hermes_home / "presence-cache.json"
        self.config = self._load_config()
        self.cache = self._load_cache()
        self.provider = WorldContextProvider(self.config, self.cache)

    def build_presence_block(
        self,
        user_message: str,
        *,
        platform: str = "",
        user_id: str = "",
    ) -> str:
        message = (user_message or "").strip()
        if not message:
            return ""

        location_ctx = self._resolve_location(message)
        search_requested = self._should_search(message)
        if self.config.get("news_attention") == "manual_only":
            search_requested = False

        nearby_requested = bool(location_ctx) and self._should_offer_nearby(message)
        if self.config.get("nearby_attention") == "off":
            nearby_requested = False

        weather_requested = bool(location_ctx) and (
            bool(location_ctx.get("coords")) or self._mentions_weather(message)
        )
        if self.config.get("weather_attention") == "off":
            weather_requested = False

        time_ctx = self._build_time_context(location_ctx)
        captured_events = self._capture_event_memory(message, time_ctx)
        captured_state_cues = self._capture_state_cues(message)
        event_carryover = self._get_upcoming_events(time_ctx)
        state_cues = self._get_recent_state_cues()
        scheduled_reminders = self._get_scheduled_reminders(time_ctx)
        search_ctx = self.provider.search(message) if search_requested else {}
        weather_ctx = self.provider.weather(location_ctx) if weather_requested else {}
        nearby_ctx = (
            self.provider.nearby(
                location_ctx,
                intent=self._extract_nearby_intent(message),
                raw_message=message,
            )
            if nearby_requested
            else {}
        )
        interaction_guidance = self._build_interaction_guidance(
            time_ctx=time_ctx,
            weather_ctx=weather_ctx,
            nearby_ctx=nearby_ctx,
            event_carryover=event_carryover or captured_events,
            state_cues=state_cues or captured_state_cues,
            scheduled_reminders=scheduled_reminders,
            location_ctx=location_ctx,
        )

        context = {
            "time_context": time_ctx,
            "location_context": {"label": location_ctx.get("label", "")} if location_ctx else {},
            "weather_context": weather_ctx,
            "nearby_context": nearby_ctx,
            "search_context": search_ctx,
            "event_carryover": event_carryover,
            "scheduled_reminders": scheduled_reminders,
            "state_cues": state_cues,
            "interaction_guidance": interaction_guidance,
            "search_requested": search_requested,
            "weather_requested": weather_requested,
            "nearby_requested": nearby_requested,
            "platform": platform,
            "user_id": user_id,
        }
        self._save_cache()
        return PresencePlanner.compose(context)

    def render_user_facing(self, text: str) -> str:
        return UserFacingRenderer.render(text)

    def _load_config(self) -> dict[str, Any]:
        data = self._load_json(self.config_path)
        base = build_default_presence_config()
        return {**base, **(data if isinstance(data, dict) else {})}

    def _load_cache(self) -> dict[str, Any]:
        data = self._load_json(self.cache_path)
        if not isinstance(data, dict):
            data = {}
        data.setdefault("search", {})
        data.setdefault("weather", {})
        data.setdefault("nearby", {})
        data.setdefault("geocoding", {})
        data.setdefault("events", [])
        data.setdefault("state_cues", [])
        return data

    @staticmethod
    def _load_json(path: Path) -> Any:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_cache(self) -> None:
        self.cache["updated_at"] = _iso(_utcnow())
        try:
            atomic_json_write(self.cache_path, self.cache)
        except Exception as exc:
            logger.debug("presence cache write failed: %s", exc)

    def _resolve_location(self, message: str) -> dict[str, Any]:
        explicit = self._extract_location(message)
        if explicit:
            self.cache["last_explicit_location"] = explicit
            return explicit
        cached = self.cache.get("last_explicit_location")
        return cached if isinstance(cached, dict) else {}

    def _extract_location(self, message: str) -> dict[str, Any]:
        lat_match = _LAT_RE.search(message)
        lon_match = _LON_RE.search(message)
        if lat_match and lon_match:
            venue = _VENUE_RE.search(message)
            address = _ADDRESS_RE.search(message)
            label = venue.group(1).strip() if venue else ""
            if address:
                label = f"{label}, {address.group(1).strip()}".strip(", ")
            return {
                "source": "location_pin",
                "coords": {
                    "latitude": float(lat_match.group(1)),
                    "longitude": float(lon_match.group(1)),
                },
                "label": label or "shared location",
            }

        coord_pair = _COORD_PAIR_RE.search(message)
        if coord_pair and (self._mentions_weather(message) or self._should_offer_nearby(message)):
            return {
                "source": "coordinate_text",
                "coords": {
                    "latitude": float(coord_pair.group(1)),
                    "longitude": float(coord_pair.group(2)),
                },
                "label": "shared coordinates",
            }

        for pattern in (_WEATHER_IN_RE, _WEATHER_ZH_RE, _LOCATION_STATEMENT_RE, _NEARBY_ZH_LOCATION_RE, _NEARBY_EN_LOCATION_RE):
            match = pattern.search(message)
            if not match:
                continue
            label = _clean_location_label(match.group(1))
            if label:
                return {"source": "explicit_text", "query": label, "label": label}
        return {}

    def _build_time_context(self, location_ctx: dict[str, Any]) -> dict[str, Any]:
        timezone_name = ""
        explicit_tz = str(os.getenv("HERMES_TIMEZONE", "")).strip()
        if explicit_tz:
            timezone_name = explicit_tz
        elif location_ctx and location_ctx.get("resolved", {}).get("timezone"):
            timezone_name = location_ctx["resolved"]["timezone"]
        elif location_ctx and location_ctx.get("timezone"):
            timezone_name = location_ctx["timezone"]
        elif ((self.cache.get("last_explicit_location") or {}).get("resolved") or {}).get("timezone"):
            timezone_name = self.cache["last_explicit_location"]["resolved"]["timezone"]
        else:
            try:
                local_tz = datetime.now().astimezone().tzinfo
                timezone_name = getattr(local_tz, "key", "") or str(local_tz or "").strip() or "UTC"
            except Exception:
                timezone_name = "UTC"

        try:
            from zoneinfo import ZoneInfo

            now_local = datetime.now(ZoneInfo(timezone_name))
        except Exception:
            try:
                now_local = datetime.now().astimezone()
                timezone_name = getattr(now_local.tzinfo, "key", "") or str(now_local.tzinfo or "").strip() or "UTC"
            except Exception:
                timezone_name = "UTC"
                now_local = _utcnow()

        hour = now_local.hour
        if 0 <= hour < 5:
            daypart = "deep night"
        elif 5 <= hour < 9:
            daypart = "early morning"
        elif 9 <= hour < 12:
            daypart = "morning"
        elif 12 <= hour < 17:
            daypart = "afternoon"
        elif 17 <= hour < 22:
            daypart = "evening"
        else:
            daypart = "late night"

        rhythm = "weekend" if now_local.weekday() >= 5 else "workday"
        return {
            "timezone": timezone_name,
            "display": now_local.strftime("%Y-%m-%d %H:%M"),
            "daypart": daypart,
            "rhythm": rhythm,
        }

    def _capture_event_memory(self, message: str, time_ctx: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.config.get("short_term_memory_enabled", True):
            return []

        timezone_name = time_ctx.get("timezone") or "UTC"
        now_local = self._now_in_timezone(timezone_name)
        captured_at = _iso(_utcnow())
        captured: list[dict[str, Any]] = []
        for clause in self._split_clauses(message):
            due = self._detect_due_reference(clause, now_local.date())
            if not due or not _COMMITMENT_RE.search(clause):
                continue
            summary = _trim(clause, 140)
            if not summary:
                continue
            key = f"{due['due_date']}::{_slugify(summary)}"
            captured.append(
                {
                    "id": key,
                    "summary": summary,
                    "due_date": due["due_date"],
                    "due_label": due["due_label"],
                    "kind": "reminder" if (_REMINDER_RE.search(clause) or _ANNIVERSARY_RE.search(clause)) else "event",
                    "captured_at": captured_at,
                }
            )

        if not captured:
            self._prune_short_term_memory(now_local.date())
            return []

        existing = [item for item in self.cache.get("events", []) if isinstance(item, dict)]
        merged: dict[str, dict[str, Any]] = {
            str(item.get("id") or f"{item.get('due_date', '')}::{_slugify(item.get('summary', ''))}"): item
            for item in existing
        }
        for item in captured:
            merged[item["id"]] = item
        items = list(merged.values())
        items.sort(key=lambda item: (item.get("due_date", ""), item.get("captured_at", "")))
        max_items = int(self.config.get("max_event_memory_items", 8) or 8)
        self.cache["events"] = items[-max_items:]
        self._prune_short_term_memory(now_local.date())
        return captured

    def _capture_state_cues(self, message: str) -> list[dict[str, Any]]:
        if not self.config.get("short_term_memory_enabled", True):
            return []

        captured_at = _iso(_utcnow())
        captured: list[dict[str, Any]] = []
        for clause in self._split_clauses(message):
            for category, pattern in _STATE_CUE_PATTERNS.items():
                if not pattern.search(clause):
                    continue
                summary = _trim(clause, 120)
                key = f"{category}::{_slugify(summary)}"
                captured.append(
                    {
                        "id": key,
                        "category": category,
                        "label": category.replace("_", " "),
                        "summary": summary,
                        "captured_at": captured_at,
                    }
                )
                break

        if not captured:
            self._prune_state_cues()
            return []

        existing = [item for item in self.cache.get("state_cues", []) if isinstance(item, dict)]
        merged = {
            str(item.get("id") or f"{item.get('category', '')}::{_slugify(item.get('summary', ''))}"): item
            for item in existing
        }
        for item in captured:
            merged[item["id"]] = item
        items = list(merged.values())
        items.sort(key=lambda item: item.get("captured_at", ""))
        max_items = int(self.config.get("max_state_cues", 8) or 8)
        self.cache["state_cues"] = items[-max_items:]
        self._prune_state_cues()
        return captured

    def _prune_short_term_memory(self, today_local: date) -> None:
        horizon = int(self.config.get("event_horizon_days", 7) or 7)
        pruned: list[dict[str, Any]] = []
        for item in self.cache.get("events", []):
            if not isinstance(item, dict):
                continue
            try:
                due = date.fromisoformat(str(item.get("due_date")))
            except Exception:
                continue
            delta = (due - today_local).days
            if -1 <= delta <= horizon:
                pruned.append(item)
        self.cache["events"] = pruned

    def _prune_state_cues(self) -> None:
        ttl_hours = int(self.config.get("state_cue_ttl_hours", 36) or 36)
        kept: list[dict[str, Any]] = []
        now = _utcnow()
        for item in self.cache.get("state_cues", []):
            if not isinstance(item, dict):
                continue
            captured_at = _parse_iso(item.get("captured_at"))
            if not captured_at:
                continue
            if (now - captured_at).total_seconds() <= ttl_hours * 3600:
                kept.append(item)
        self.cache["state_cues"] = kept

    def _get_upcoming_events(self, time_ctx: dict[str, Any]) -> list[dict[str, Any]]:
        timezone_name = time_ctx.get("timezone") or "UTC"
        today_local = self._now_in_timezone(timezone_name).date()
        self._prune_short_term_memory(today_local)
        items = [item for item in self.cache.get("events", []) if isinstance(item, dict)]
        items.sort(key=lambda item: (item.get("due_date", ""), item.get("captured_at", "")))
        return items[: int(self.config.get("max_event_memory_items", 8) or 8)]

    def _get_recent_state_cues(self) -> list[dict[str, Any]]:
        self._prune_state_cues()
        items = [item for item in self.cache.get("state_cues", []) if isinstance(item, dict)]
        items.sort(key=lambda item: item.get("captured_at", ""))
        return list(reversed(items[: int(self.config.get("max_state_cues", 8) or 8)]))

    def _get_scheduled_reminders(self, time_ctx: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.config.get("cron_memory_enabled", True):
            return []
        if self.config.get("reminder_attention") == "off":
            return []

        jobs_path = self.hermes_home / "cron" / "jobs.json"
        if not jobs_path.exists():
            return []

        try:
            raw_jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        if not isinstance(raw_jobs, list):
            return []

        timezone_name = time_ctx.get("timezone") or "UTC"
        now_local = self._now_in_timezone(timezone_name)
        horizon_hours = int(self.config.get("cron_horizon_hours", 36) or 36)
        upcoming: list[dict[str, Any]] = []

        for job in raw_jobs:
            if not isinstance(job, dict) or not job.get("enabled", True):
                continue
            next_run = self._parse_job_datetime(job.get("next_run_at"), timezone_name)
            if not next_run:
                continue
            delta_hours = (next_run - now_local).total_seconds() / 3600
            if delta_hours < -1 or delta_hours > horizon_hours:
                continue

            summary = _trim(str(job.get("name") or job.get("prompt") or "scheduled reminder"), 120)
            if not summary:
                continue
            upcoming.append(
                {
                    "id": str(job.get("id") or ""),
                    "summary": summary,
                    "due_at": next_run.isoformat(),
                    "due_label": self._format_due_label(next_run, now_local),
                    "schedule_display": str(job.get("schedule_display") or ""),
                }
            )

        upcoming.sort(key=lambda item: item.get("due_at", ""))
        return upcoming[: int(self.config.get("max_cron_items", 4) or 4)]

    def _build_interaction_guidance(
        self,
        *,
        time_ctx: dict[str, Any],
        weather_ctx: dict[str, Any],
        nearby_ctx: dict[str, Any],
        event_carryover: list[dict[str, Any]],
        state_cues: list[dict[str, Any]],
        scheduled_reminders: list[dict[str, Any]],
        location_ctx: dict[str, Any],
    ) -> dict[str, Any]:
        topic_suggestions: list[str] = []
        hints: list[str] = []
        tone = "natural"
        pace = "normal pace"
        initiative_style = str(self.config.get("initiative_style") or "balanced")
        social_energy = str(self.config.get("social_energy") or "balanced")
        reminder_attention = str(self.config.get("reminder_attention") or "gentle")
        weather_attention = str(self.config.get("weather_attention") or "contextual")
        nearby_attention = str(self.config.get("nearby_attention") or "helpful")
        voice_strategy = str(self.config.get("voice_style") or "adaptive")

        daypart = time_ctx.get("daypart", "")
        rhythm = time_ctx.get("rhythm", "")
        if daypart in {"deep night", "late night"}:
            hints.append("Keep replies a little softer and less demanding; avoid trapping them in a long thread unless they clearly want that.")
            tone = "soft"
            pace = "slower"
        elif rhythm == "weekend" and daypart in {"morning", "afternoon"}:
            hints.append("A slightly warmer, more proactive check-in can feel natural.")
            tone = "light"

        state_categories = {item.get("category") for item in state_cues}
        if "tired" in state_categories or "busy" in state_categories:
            hints.append("They seem low-energy or occupied, so keep it considerate and practical.")
            tone = "gentle"
            pace = "unhurried"
        if "stressed" in state_categories or "unwell" in state_categories:
            hints.append("Lean more toward comfort, reassurance, and low-pressure follow-ups than playful escalation.")
            tone = "calm"
            pace = "slower"
        if "excited" in state_categories and tone == "natural":
            tone = "bright"

        condition = str(weather_ctx.get("condition") or "")
        if weather_attention != "off" and ("rain" in condition or "snow" in condition or "storm" in condition):
            hints.append("A small weather-aware practical suggestion or extra bit of care will feel grounded.")
            topic_suggestions.append("If it fits, fold in one practical weather-aware suggestion instead of only reacting emotionally.")

        if event_carryover:
            soonest = event_carryover[0]
            due_label = soonest.get("due_label", "soon")
            summary = soonest.get("summary", "")
            if summary:
                if soonest.get("kind") == "reminder" and reminder_attention != "off":
                    topic_suggestions.append(f"If it fits, gently remember this with them: {summary}")
                else:
                    topic_suggestions.append(f"Gently check in about {due_label}'s plan: {summary}")

        if scheduled_reminders and reminder_attention != "off":
            soonest_job = scheduled_reminders[0]
            summary = soonest_job.get("summary", "")
            due_label = soonest_job.get("due_label", "soon")
            if summary:
                topic_suggestions.append(f"There is a scheduled follow-up {due_label}: {summary}")

        nearby_items = nearby_ctx.get("items") or []
        if nearby_items and nearby_attention != "off":
            first_title = nearby_items[0].get("title") or nearby_items[0].get("description") or ""
            if first_title:
                topic_suggestions.append(
                    f"If they want a practical suggestion, you can naturally mention {first_title} around {nearby_ctx.get('label', location_ctx.get('label', 'there'))}."
                )
        elif nearby_attention != "off" and location_ctx.get("source") == "location_pin" and location_ctx.get("label"):
            topic_suggestions.append("They shared a live location pin, so asking one light nearby-preference question would feel natural.")

        interest_topics = [str(topic).strip() for topic in (self.config.get("interest_topics") or []) if str(topic).strip()]
        if self.config.get("news_attention") == "proactive" and interest_topics:
            topic_suggestions.append(f"If the moment is open, you can lightly connect to one of their likely interest lanes: {', '.join(interest_topics[:3])}.")

        if initiative_style == "reserved":
            hints.append("Do not push the conversation forward too aggressively; keep initiative subtle.")
            topic_suggestions = topic_suggestions[:1]
        elif initiative_style == "proactive":
            hints.append("It is okay to gently offer one extra thread or check-in without waiting to be asked.")
            if social_energy == "warm":
                tone = "warm"

        if social_energy == "soft":
            tone = "soft" if tone == "natural" else tone
            pace = "slower" if pace == "normal pace" else pace
        elif social_energy == "playful" and tone in {"natural", "light"}:
            tone = "bright"

        if voice_strategy == "steady":
            pace = "normal pace"
        elif voice_strategy == "soft":
            tone = "soft"
            pace = "slower"

        return {
            "initiative_hint": " ".join(dict.fromkeys(hints)).strip(),
            "topic_suggestions": list(dict.fromkeys(topic_suggestions)),
            "voice_style": {"tone": tone, "pace": pace} if self.config.get("voice_style_enabled", True) else {},
        }

    @staticmethod
    def _split_clauses(message: str) -> list[str]:
        clauses = [_trim(part.strip(), 160) for part in _EVENT_CLAUSE_SPLIT_RE.split(message or "")]
        return [clause for clause in clauses if clause]

    @staticmethod
    def _detect_due_reference(clause: str, today_local: date) -> dict[str, str] | None:
        lowered = clause.lower()
        iso_match = _DATE_ISO_RE.search(clause)
        if iso_match:
            year, month, day = (int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))
            try:
                due = date(year, month, day)
                return {"due_date": due.isoformat(), "due_label": due.strftime("%Y-%m-%d")}
            except ValueError:
                return None
        zh_match = _DATE_ZH_RE.search(clause)
        if zh_match:
            year = int(zh_match.group(1) or today_local.year)
            month = int(zh_match.group(2))
            day = int(zh_match.group(3))
            try:
                due = date(year, month, day)
                if not zh_match.group(1) and due < today_local:
                    due = date(today_local.year + 1, month, day)
                return {"due_date": due.isoformat(), "due_label": due.strftime("%Y-%m-%d")}
            except ValueError:
                return None
        if any(marker in clause for marker in _TODAY_MARKERS) or any(marker in lowered for marker in _TODAY_MARKERS):
            return {"due_date": today_local.isoformat(), "due_label": "today"}
        if any(marker in clause for marker in _TOMORROW_MARKERS) or any(marker in lowered for marker in _TOMORROW_MARKERS):
            return {"due_date": (today_local + timedelta(days=1)).isoformat(), "due_label": "tomorrow"}
        if any(marker in clause for marker in _DAY_AFTER_MARKERS) or any(marker in lowered for marker in _DAY_AFTER_MARKERS):
            return {"due_date": (today_local + timedelta(days=2)).isoformat(), "due_label": "day after tomorrow"}
        if any(marker in clause for marker in _WEEKEND_MARKERS) or any(marker in lowered for marker in _WEEKEND_MARKERS):
            days_until_weekend = (5 - today_local.weekday()) % 7
            due = today_local + timedelta(days=days_until_weekend)
            return {"due_date": due.isoformat(), "due_label": "this weekend"}
        if any(marker in clause for marker in _NEXT_WEEK_MARKERS) or any(marker in lowered for marker in _NEXT_WEEK_MARKERS):
            due = today_local + timedelta(days=7)
            return {"due_date": due.isoformat(), "due_label": "next week"}
        return None

    @staticmethod
    def _now_in_timezone(timezone_name: str) -> datetime:
        try:
            from zoneinfo import ZoneInfo

            return datetime.now(ZoneInfo(timezone_name))
        except Exception:
            return _utcnow()

    @staticmethod
    def _parse_job_datetime(raw: Any, timezone_name: str) -> datetime | None:
        if not raw:
            return None
        try:
            text = str(raw)
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        try:
            from zoneinfo import ZoneInfo

            target_tz = ZoneInfo(timezone_name)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=target_tz)
            return parsed.astimezone(target_tz)
        except Exception:
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    @staticmethod
    def _format_due_label(due_at: datetime, now_local: datetime) -> str:
        if due_at.date() == now_local.date():
            return f"today at {due_at.strftime('%H:%M')}"
        if due_at.date() == (now_local.date() + timedelta(days=1)):
            return f"tomorrow at {due_at.strftime('%H:%M')}"
        return due_at.strftime("%Y-%m-%d %H:%M")

    def get_tts_overrides(self, reply_text: str = "") -> dict[str, Any]:
        timezone_name = str(os.getenv("HERMES_TIMEZONE", "")).strip() or "UTC"
        last_location = self.cache.get("last_explicit_location") or {}
        if isinstance(last_location, dict):
            timezone_name = (
                str((last_location.get("resolved") or {}).get("timezone") or last_location.get("timezone") or timezone_name)
                or timezone_name
            )

        now_local = self._now_in_timezone(timezone_name)
        state_cues = self._get_recent_state_cues()
        speed = 1.0
        pitch = 0
        tone = "natural"

        if now_local.hour < 6 or now_local.hour >= 23:
            speed -= 0.08
            tone = "soft"

        categories = {item.get("category") for item in state_cues}
        if {"tired", "busy"} & categories:
            speed -= 0.06
            tone = "gentle"
        if {"stressed", "unwell"} & categories:
            speed -= 0.08
            tone = "calm"
            pitch -= 1
        if "excited" in categories:
            speed += 0.04
            tone = "bright"
            pitch += 1

        if _TTS_CALM_RE.search(reply_text or ""):
            speed -= 0.04
            tone = "calm"
        elif _TTS_BRIGHT_RE.search(reply_text or ""):
            speed += 0.04
            tone = "bright"
            pitch += 1

        speed = round(max(0.8, min(1.15, speed)), 2)
        overrides: dict[str, Any] = {"speed": speed, "tone": tone}
        provider_overrides: dict[str, dict[str, Any]] = {}
        if pitch:
            provider_overrides["minimax"] = {"pitch": max(-4, min(4, pitch))}
        if provider_overrides:
            overrides["provider_overrides"] = provider_overrides
        return overrides

    @staticmethod
    def _mentions_weather(message: str) -> bool:
        return bool(_WEATHER_TRIGGER_RE.search(message or ""))

    @staticmethod
    def _should_offer_nearby(message: str) -> bool:
        return bool(_NEARBY_TRIGGER_RE.search(message or ""))

    @staticmethod
    def _extract_nearby_intent(message: str) -> str:
        match = _NEARBY_LABEL_RE.search(message or "")
        if match:
            return match.group(1)
        if _RAINY_NEARBY_RE.search(message or ""):
            return "适合躲雨待一会儿的地方"
        return "可以顺路去一下的地方"

    @staticmethod
    def _should_search(message: str) -> bool:
        if not _SEARCH_TRIGGER_RE.search(message or ""):
            return False
        return _looks_like_question(message) or "最新" in message or "news" in message.lower()
