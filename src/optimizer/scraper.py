#!/usr/bin/env python3
"""Scrape SteamDeckHQ for recommended game settings."""

import json
import re
import subprocess
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".cache" / "deck-auto-tdp"
HEADERS = "User-Agent: deck-auto-tdp/1.0"


def _curl_get(url: str) -> str:
    result = subprocess.run(
        ["curl", "-s", "-H", HEADERS, url],
        capture_output=True, text=True, timeout=15,
    )
    return result.stdout if result.returncode == 0 else ""


def search_steamdeckhq(game_name: str) -> Optional[str]:
    query = game_name.replace(" ", "+")
    html = _curl_get(f"https://steamdeckhq.com/?s={query}")
    if not html:
        return None
    match = re.search(r'href="(https://steamdeckhq\.com/game-reviews/[^"]+)"', html)
    return match.group(1) if match else None


def scrape_settings(review_url: str) -> dict:
    html = _curl_get(review_url)
    if not html:
        return {}

    settings = {}

    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text)

    proton_match = re.search(r'[Pp]roton\s*(GE[- ]?\d[\w.-]*|\d[\w.-]*)', text)
    if proton_match:
        settings["proton"] = proton_match.group(1).strip()

    fps_match = re.search(r'(?:fps|frame)\s*(?:limit|cap|lock)[:\s]*(\d{2,3})', text, re.IGNORECASE)
    if fps_match:
        settings["fps_limit"] = int(fps_match.group(1))

    fsr_match = re.search(r'FSR\s*(on|off|enabled|disabled)', text, re.IGNORECASE)
    if fsr_match:
        val = fsr_match.group(1).lower()
        settings["fsr"] = val in ("on", "enabled")

    tdp_match = re.search(r'TDP[:\s]*(\d{1,2})\s*[Ww]', text)
    if tdp_match:
        settings["tdp"] = int(tdp_match.group(1))

    gpu_match = re.search(r'GPU\s*(?:clock|freq)[:\s]*(\d{3,4})\s*(?:MHz)?', text, re.IGNORECASE)
    if gpu_match:
        settings["gpu_clock"] = int(gpu_match.group(1))

    for preset in ["low", "medium", "high", "ultra"]:
        if re.search(rf'(?:graphics|preset|quality)[:\s]*{preset}', text, re.IGNORECASE):
            settings["graphics_preset"] = preset
            break

    res_match = re.search(r'(?:resolution|render)[:\s]*(1280x800|800p|720p|540p)', text, re.IGNORECASE)
    if res_match:
        settings["resolution"] = res_match.group(1)

    for setting_name in ["shadows", "anti.?aliasing", "textures", "reflections", "volumetric"]:
        match = re.search(rf'{setting_name}[:\s]*(off|low|medium|high|ultra)', text, re.IGNORECASE)
        if match:
            key = re.sub(r'[.?]', '', setting_name)
            settings[key] = match.group(1).lower()

    settings["source"] = review_url

    if settings.get("fps_limit") and settings["fps_limit"] > 60:
        settings.pop("fps_limit")

    return settings


def get_community_settings(game_name: str, app_id: str = None) -> dict:
    if app_id:
        try:
            from .sharedeck import get_sharedeck_settings
            from config import load_config
            display = load_config().get("display_model", "lcd")
            sd = get_sharedeck_settings(app_id, display_model=display)
            useful = [k for k in sd if k not in ("source", "report_count") and sd[k] is not None]
            if len(useful) >= 2:
                return sd
        except Exception as e:
            logger.warning(f"ShareDeck failed: {e}")

    cache_file = CACHE_DIR / f"{re.sub(r'[^a-zA-Z0-9]', '_', game_name.lower())}.json"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text())
        except json.JSONDecodeError:
            pass

    url = search_steamdeckhq(game_name)
    if not url:
        logger.info(f"No SteamDeckHQ review for '{game_name}'")
        return {}

    settings = scrape_settings(url)
    if settings:
        cache_file.write_text(json.dumps(settings, indent=2))
        logger.info(f"Scraped settings for '{game_name}': {settings}")

    return settings
