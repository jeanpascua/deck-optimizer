#!/usr/bin/env python3
"""AI-based settings prediction for games without community data."""

import json
import logging
import subprocess
import sys
from pathlib import Path
import requests
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import load_config

logger = logging.getLogger(__name__)

_config = load_config()
OLLAMA_URL = _config["ollama_url"]
OLLAMA_MODEL = _config["ollama_model"]
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

CRITICAL: Match TDP to the game's ACTUAL demand. Do NOT default to 13W for everything.

TDP (give ONE number, not a range):
- 2D/pixel/card/retro/SNES/GBA/visual novel: 4-5W (e.g. Slay the Spire=5, Chrono Trigger=4, Stardew Valley=5, Undertale=4)
- Light 3D/indie/older 3D: 7-9W (e.g. Portal 2=8, Hades=9, Celeste=5, Hollow Knight=6, Core Keeper=6)
- Medium 3D/action RPG: 10-12W (e.g. Witcher 3=12, MH Rise=11, Outer Wilds=10)
- Heavy AAA/2022+: 13-15W (e.g. Cyberpunk=15, Elden Ring=14, Hogwarts Legacy=15, FF7 Rebirth=15)

GPU clock (give ONE number):
- 2D/retro: 400-600 MHz
- Light 3D/indie: 600-800 MHz
- Medium 3D: 800-1200 MHz
- Heavy AAA: 1200-1600 MHz

FPS limit:
- Heavy AAA: 30fps
- Medium 3D: 40fps
- Light/2D/indie: 60fps
- Allowed: 15, 30, 40, 60

FSR: true ONLY for demanding 3D games. false for 2D/pixel/retro — they run at native res fine.
Half Rate Shading: true ONLY as last resort for heaviest games. false for everything else.
Allow Tearing: true for competitive/fast-paced. false for casual/story/turn-based.
Disable Frame Limit: false always unless benchmarking.
Scaling Mode options: auto, integer, fit, stretch, fill. Use "fit" for most games. "integer" for pixel art. "stretch" or "fill" rarely.
Scaling Filter (Steam Deck LCD labels): "sharp" for 3D games (FSR/NIS upscaling). "linear" for most games. "pixel" for retro/pixel art.
Sharpness (0-5): only applies when scaling_filter is "sharp". 3 is balanced. 5 is sharpest. 0 is softest.

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
  "allow_tearing": <true/false>,
  "disable_frame_limit": <true/false>,
  "scaling_mode": "<auto/integer/fit/stretch/fill>",
  "scaling_filter": "<linear/pixel/sharp>",
  "sharpness": <0-5 only when scaling_filter is sharp, omit otherwise>,
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
