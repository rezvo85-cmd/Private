from __future__ import annotations

import re
from typing import Any

import requests

from r20_web_tools import research as web_research, status as web_status
from tool_system import safe_calculate, validate_json, code_sanity

CATALOG = {
    "web_search": "Searches the live web with SearXNG.",
    "web_reader": "Opens and cleans webpages with Crawl4AI.",
    "weather": "Gets current weather from Open-Meteo and can fall back to web research.",
    "calculator": "Deterministic arithmetic.",
    "json": "Validates and formats JSON.",
    "documents": "Local PDF/DOCX/XLSX/PPTX extraction through RONN document intelligence.",
    "vision": "Understands attached images and screenshots.",
    "memory": "Retrieves persistent RONN memory and project context.",
    "code_sanity": "Runs deterministic syntax/sanity checks where supported.",
    "web_fallback": "Groq Compound web_search / visit_website fallback.",
}

WEATHER_CODES = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "foggy", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "freezing drizzle", 57: "freezing drizzle", 61: "light rain", 63: "rain",
    65: "heavy rain", 66: "freezing rain", 67: "freezing rain", 71: "light snow",
    73: "snow", 75: "heavy snow", 77: "snow grains", 80: "rain showers",
    81: "rain showers", 82: "heavy rain showers", 85: "snow showers",
    86: "heavy snow showers", 95: "thunderstorms", 96: "thunderstorms with hail",
    99: "thunderstorms with hail",
}


def _clean(text: str, limit: int = 1200) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def _weather_location(message: str) -> str:
    text = _clean(message)
    patterns = [
        r"(?i)\b(?:weather|forecast)\s+(?:like\s+)?(?:in|for|at)\s+(.+?)(?:\?|$)",
        r"(?i)\b(?:what(?:'s| is)\s+the\s+weather\s+(?:like\s+)?(?:in|for|at))\s+(.+?)(?:\?|$)",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return _clean(m.group(1), 180).strip(" .,!?:;")
    return ""


def weather(message: str) -> dict[str, Any]:
    location = _weather_location(message)
    if not location:
        return {"ok": False, "reason": "location_missing"}

    geo = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": location, "count": 1, "language": "en", "format": "json"},
        timeout=(5, 15),
        headers={"User-Agent": "RONN/20 weather"},
    )
    geo.raise_for_status()
    rows = (geo.json() or {}).get("results") or []
    if not rows:
        return {"ok": False, "reason": "location_not_found", "location": location}
    place = rows[0]
    lat, lon = place.get("latitude"), place.get("longitude")
    label = ", ".join(x for x in [place.get("name"), place.get("admin1"), place.get("country")] if x)

    wx = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "timezone": "auto",
        },
        timeout=(5, 15),
        headers={"User-Agent": "RONN/20 weather"},
    )
    wx.raise_for_status()
    data = wx.json() or {}
    cur = data.get("current") or {}
    code = int(cur.get("weather_code") or 0)
    card = {
        "type": "weather",
        "location": label or location,
        "temperature_f": cur.get("temperature_2m"),
        "feels_like_f": cur.get("apparent_temperature"),
        "condition": WEATHER_CODES.get(code, "current conditions"),
        "wind_mph": cur.get("wind_speed_10m"),
        "observed_at": cur.get("time"),
        "timezone": data.get("timezone"),
    }
    evidence = (
        "RONN WEATHER EVIDENCE — current structured data from Open-Meteo.\n"
        f"Location: {card['location']}\n"
        f"Temperature: {card['temperature_f']} F\n"
        f"Feels like: {card['feels_like_f']} F\n"
        f"Condition: {card['condition']}\n"
        f"Wind: {card['wind_mph']} mph\n"
        f"Observed: {card['observed_at']} {card['timezone'] or ''}\n"
        "Source: Open-Meteo current weather + geocoding APIs."
    )
    return {
        "ok": True,
        "tool": "weather",
        "evidence": evidence,
        "presentation": card,
        "sources": [{"title": "Open-Meteo", "url": "https://open-meteo.com/"}],
    }


def plan(message: str, *, needs_live=False, has_files=False, has_images=False) -> list[str]:
    low = _clean(message).lower()
    chosen: list[str] = []
    if has_images:
        chosen.append("vision")
    if has_files:
        chosen.append("documents")
    if "weather" in low or "forecast" in low:
        chosen.append("weather")
    elif needs_live:
        chosen.extend(["web_search", "web_reader"])
    if re.fullmatch(r"[\d\s+\-*/().%^]+", low):
        chosen.append("calculator")
    if "json" in low and ("validate" in low or "check" in low):
        chosen.append("json")
    chosen.append("memory")
    return list(dict.fromkeys(chosen))


def execute(message: str, *, depth="smart", needs_live=False, has_files=False, has_images=False) -> dict[str, Any]:
    chosen = plan(message, needs_live=needs_live, has_files=has_files, has_images=has_images)
    result: dict[str, Any] = {
        "planned": chosen,
        "executed": [],
        "evidence": "",
        "presentation": None,
        "sources": [],
        "web_research": {},
        "errors": [],
    }

    if "weather" in chosen:
        try:
            w = weather(message)
            if w.get("ok"):
                result["executed"].append("weather")
                result["evidence"] = w.get("evidence", "")
                result["presentation"] = w.get("presentation")
                result["sources"] = w.get("sources") or []
                return result
            result["errors"].append("weather:" + str(w.get("reason") or "failed"))
        except Exception as exc:
            result["errors"].append("weather:" + exc.__class__.__name__)

    if needs_live:
        try:
            web = web_research(message, depth)
            result["web_research"] = web
            if web.get("evidence"):
                result["executed"].extend(["web_search", "web_reader"])
                result["evidence"] = web.get("evidence", "")
                result["sources"] = web.get("sources") or []
        except Exception as exc:
            result["errors"].append("web:" + exc.__class__.__name__)

    return result


def status() -> dict[str, Any]:
    return {
        "catalog": dict(CATALOG),
        "web": web_status(),
        "automatic_selection": True,
        "tool_count": len(CATALOG),
    }
