#!/usr/bin/env python3
"""Main optimizer — combines community settings + AI predictions."""

import json
import logging
import re
import requests
from pathlib import Path
from typing import Optional

from .scraper import get_community_settings
from .ai_predict import predict_settings, get_steam_info

logger = logging.getLogger(__name__)

STEAM_LIBRARY = Path.home() / ".local" / "share" / "Steam" / "steamapps"
SETTINGS_DIR = Path.home() / ".config" / "deck-auto-tdp" / "settings"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:14b"


def get_installed_games() -> list[dict]:
    games = []
    if not STEAM_LIBRARY.exists():
        logger.warning(f"Steam library not found at {STEAM_LIBRARY}")
        return games
    for manifest in STEAM_LIBRARY.glob("appmanifest_*.acf"):
        text = manifest.read_text()
        app_id = re.search(r'"appid"\s+"(\d+)"', text)
        name = re.search(r'"name"\s+"([^"]+)"', text)
        if app_id and name:
            games.append({"app_id": app_id.group(1), "name": name.group(1)})
    return sorted(games, key=lambda g: g["name"])


def get_library_from_api(steam_id: str) -> list[dict]:
    try:
        resp = requests.get(
            f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
            f"?key=&steamid={steam_id}&include_appinfo=1&include_played_free_games=1",
            timeout=10,
        )
        data = resp.json().get("response", {}).get("games", [])
        return [{"app_id": str(g["appid"]), "name": g.get("name", f"App_{g['appid']}")} for g in data]
    except Exception:
        return []


def optimize_game(app_id: str, game_name: str, existing_profiles: dict = None) -> dict:
    community = get_community_settings(game_name)

    if community and len(community) > 2:
        result = community.copy()
        result["method"] = "community"
        return result

    ai = predict_settings(app_id, game_name, existing_profiles)
    if ai:
        ai["method"] = "ai"
        return ai

    return {"method": "none", "reason": "No data available"}


def optimize_library(games: list[dict], existing_profiles: dict = None) -> dict:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    all_settings = {}

    for game in games:
        app_id = game["app_id"]
        name = game["name"]
        logger.info(f"Optimizing: {name} ({app_id})")

        settings = optimize_game(app_id, name, existing_profiles)
        all_settings[app_id] = {"name": name, **settings}

    output = SETTINGS_DIR / "all_settings.json"
    output.write_text(json.dumps(all_settings, indent=2))
    logger.info(f"Saved {len(all_settings)} game settings to {output}")

    return all_settings


def format_discord(all_settings: dict) -> list[str]:
    messages = []
    lines = []

    for app_id, s in all_settings.items():
        name = s.get("name", app_id)
        method = s.get("method", "?")
        icon = {"community": "✅", "ai": "🤖", "none": "❓"}.get(method, "?")

        parts = [f"{icon} **{name}**"]
        if s.get("tdp"):
            parts.append(f"TDP: {s['tdp']}W")
        if s.get("fps_limit"):
            parts.append(f"FPS: {s['fps_limit']}")
        if s.get("graphics_preset"):
            parts.append(f"Preset: {s['graphics_preset']}")
        if s.get("fsr") is not None:
            parts.append(f"FSR: {'on' if s['fsr'] else 'off'}")
        if s.get("resolution"):
            parts.append(f"Res: {s['resolution']}")
        if s.get("reason"):
            parts.append(f"_{s['reason']}_")

        line = " | ".join(parts)
        if sum(len(l) for l in lines) + len(line) > 1800:
            messages.append("\n".join(lines))
            lines = []
        lines.append(line)

    if lines:
        messages.append("\n".join(lines))
    return messages
