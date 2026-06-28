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


def predict_settings(app_id: str, game_name: str, existing_profiles: dict = None,
                     session_history: list = None, sharedeck_data: dict = None) -> dict:
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

    session_context = ""
    if session_history:
        recent = session_history[-3:]
        session_lines = [
            f"- GPU avg:{s.get('gpu_busy_avg')}% power:{s.get('power_watts_avg')}W temp:{s.get('temp_c_avg')}°C battery_drain:{s.get('battery_drain_pct')}% duration:{s.get('session_duration_min')}min"
            for s in recent
        ]
        session_context = "Recent play sessions:\n" + "\n".join(session_lines)

    sharedeck_context = ""
    if sharedeck_data and sharedeck_data.get("report_count"):
        sharedeck_context = f"ShareDeck community data ({sharedeck_data['report_count']} reports): " + json.dumps({k: v for k, v in sharedeck_data.items() if k not in ('source',)}, indent=2)

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
{session_context}
{sharedeck_context}

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


def analyze_session(app_id: str, game_name: str, current_settings: dict,
                    session_stats: dict, sharedeck_data: dict = None) -> dict:
    sd_context = ""
    if sharedeck_data and sharedeck_data.get("report_count"):
        sd_context = f"ShareDeck community ({sharedeck_data['report_count']} reports): {json.dumps(sharedeck_data)}"

    fps_rules = ""
    if session_stats.get("fps_avg") is not None:
        fps_rules = f"""- fps_avg vs fps_limit: if fps_avg < fps_limit * 0.85, game can't hit target — lower fps_limit or raise TDP
- fps_avg > fps_limit * 0.98 and GPU avg < 60% = fps_limit too conservative, could raise it
- fps_min far below fps_avg = stuttering, raise TDP or lower gpu_clock
"""

    prompt = f"""You are a Steam Deck optimization expert analyzing a gameplay session.

Game: {game_name}
Current settings: {json.dumps(current_settings)}
Session performance: {json.dumps(session_stats)}
{sd_context}

Rules:
- GPU avg < 60% and TDP > 6W = TDP too high, lower it
- GPU avg > 90% = GPU bottlenecked, raise TDP or lower graphics
- Temp avg > 80°C = overheating, lower TDP/GPU clock
- Battery drain > 50% in < 60 min = poor battery life, lower TDP
- If ShareDeck data available, prefer their tested values
{fps_rules}
Output ONLY valid JSON:
{{
  "adjustments": {{only include fields that should change, e.g. "tdp": 10, "fps_limit": 30}},
  "recommendation": "<1-2 sentences explaining what to change and why>",
  "confidence": <0.0-1.0>
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
            result = json.loads(json_match)
            logger.info(f"AI session analysis for '{game_name}': {result}")
            return result
    except Exception as e:
        logger.warning(f"AI session analysis failed for '{game_name}': {e}")

    return {}
