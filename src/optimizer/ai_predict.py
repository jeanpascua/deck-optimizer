#!/usr/bin/env python3
"""AI-based settings prediction for games without community data."""

import json
import logging
import subprocess
import requests
from typing import Optional

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "gemma3:4b"
STEAM_API = "https://store.steampowered.com/api/appdetails?appids={}"


def get_steam_info(app_id: str) -> dict:
    try:
        resp = requests.get(STEAM_API.format(app_id), timeout=10)
        data = resp.json()
        if data.get(app_id, {}).get("success"):
            info = data[app_id]["data"]
            return {
                "name": info.get("name", ""),
                "genres": [g["description"] for g in info.get("genres", [])],
                "categories": [c["description"] for c in info.get("categories", [])][:5],
                "requirements": info.get("pc_requirements", {}).get("minimum", ""),
                "release_date": info.get("release_date", {}).get("date", ""),
            }
    except Exception as e:
        logger.warning(f"Failed to get Steam info for {app_id}: {e}")
    return {}


def predict_settings(app_id: str, game_name: str, existing_profiles: dict = None) -> dict:
    steam_info = get_steam_info(app_id)

    similar_profiles = ""
    if existing_profiles:
        learned = [
            f"- {p.game_name}: {p.learned_tdp}W, {p.target_fps}fps"
            for p in existing_profiles.values()
            if p.learned_tdp is not None
        ][:10]
        if learned:
            similar_profiles = "Already learned profiles:\n" + "\n".join(learned)

    prompt = f"""You are a Steam Deck optimization expert. Predict optimal settings for this game.

Steam Deck hardware (2026):
- APU: AMD Van Gogh — 4-core Zen 2 CPU + 8 RDNA 2 GPU CUs
- GPU clock: 200-1600 MHz (higher = more power, lower can improve stability)
- RAM: 16GB LPDDR5
- Display: 1280x800 LCD 60Hz max
- TDP range: 4W-15W (battery life vs performance tradeoff)
- FSR: system-level toggle, upscales from lower res
- Half Rate Shading: reduces texture quality for FPS boost
- SteamOS (Linux, Proton for Windows games)

TDP guidelines (give ONE number, not a range):
- 2D/pixel art/card games (Slay the Spire, Celeste): 4-6W
- Light 3D/older games (Stardew Valley, Portal 2): 7-9W
- Medium 3D (Witcher 3, MH Rise, Hades): 10-12W
- Heavy AAA (Cyberpunk, Elden Ring, Hogwarts Legacy): 13-15W

GPU clock guidelines (give ONE number):
- 2D/light games: 400-800 MHz
- Medium 3D: 800-1200 MHz
- Heavy AAA: 1200-1600 MHz
- Tip: lowering GPU clock below 1600 can stabilize FPS and save battery

FPS limit guidelines:
- Heavy AAA: 30fps (saves battery, stable)
- Medium 3D: 40fps (good balance)
- Light/2D games: 60fps
- Allowed values: 15, 30, 40, 60 (LCD model, 60Hz max)

FSR: enable for demanding 3D games running below native res. Disable for 2D/pixel art/native-res games.
Half Rate Shading: enable only for very demanding games as last resort.

Game: {game_name}
Steam info: {json.dumps(steam_info, indent=2) if steam_info else 'unavailable'}
{similar_profiles}

Output ONLY valid JSON. Give single values, NOT ranges:
{{
  "tdp": <single number 4-15>,
  "gpu_clock": <single number 200-1600>,
  "fps_limit": <15 or 30 or 40 or 60>,
  "fsr": <true/false>,
  "half_rate_shading": <true/false>,
  "graphics_preset": "<low/medium/high>",
  "resolution": "1280x800",
  "shadows": "<off/low/medium/high>",
  "antialiasing": "<off/low/medium/high>",
  "textures": "<low/medium/high>",
  "reason": "<1 sentence why>"
}}"""

    try:
        resp = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 200},
        }, timeout=30)
        raw = resp.json().get("response", "")

        json_match = raw[raw.find("{"):raw.rfind("}") + 1]
        if json_match:
            settings = json.loads(json_match)
            settings["source"] = "ai_prediction"
            logger.info(f"AI predicted settings for '{game_name}': {settings}")
            return settings
    except Exception as e:
        logger.warning(f"AI prediction failed for '{game_name}': {e}")

    return {}
