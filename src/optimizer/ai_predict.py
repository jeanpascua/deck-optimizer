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

Game: {game_name}
Steam info: {json.dumps(steam_info, indent=2) if steam_info else 'unavailable'}
{similar_profiles}

Output ONLY valid JSON with these fields (omit if unsure):
{{
  "tdp": <8-15 watts>,
  "gpu_clock": <200-1600 MHz>,
  "fps_limit": <30 or 40 or 60>,
  "fsr": <true/false>,
  "graphics_preset": "<low/medium/high>",
  "resolution": "<1280x800 or 800p>",
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
