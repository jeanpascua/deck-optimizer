#!/usr/bin/env python3
"""AI-based settings prediction for games without community data."""

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import load_config
from optimizer.netutil import get_json, post_json

logger = logging.getLogger(__name__)

_config = load_config()
OLLAMA_URL = _config["ollama_url"]
OLLAMA_MODEL = _config["ollama_model"]
STEAM_API = "https://store.steampowered.com/api/appdetails?appids={}"


def get_steam_info(app_id: str) -> dict:
    try:
        data = get_json(STEAM_API.format(app_id), timeout=10)
        # Steam sometimes keys the response by a different (parent) appid, e.g. 582010 -> 1390430
        entry = data.get(app_id) or next(iter(data.values()), {})
        if entry.get("success"):
            info = entry["data"]
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

{STEAM_MENU_OPTIONS}
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
        resp = post_json(OLLAMA_URL, {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 200},
        }, timeout=30)
        raw = resp.get("response", "")

        json_match = raw[raw.find("{"):raw.rfind("}") + 1]
        if json_match:
            settings = _normalize_to_menu(json.loads(json_match))
            settings["source"] = "ai_prediction"
            logger.info(f"AI predicted settings for '{game_name}': {settings}")
            return settings
    except Exception as e:
        logger.warning(f"AI prediction failed for '{game_name}': {e}")

    return {}


# The Steam Deck Quick Access > Performance menu (SteamOS 3.8) — the only values the AI may suggest
STEAM_MENU_OPTIONS = """Steam Deck Quick Access > Performance menu (SteamOS 3.8). Use ONLY these keys and values:
- fps_limit: 10-60
- half_rate_shading: true/false
- allow_tearing: true/false
- gpu_clock: 200-1600 (MHz, Manual GPU Clock)
- scaling_mode: auto, integer, fit, stretch, fill
- scaling_filter: linear, pixel, sharp ("sharp" is AMD FSR upscaling; there is NO separate "fsr" setting)
- sharpness: 0-5, only with scaling_filter "sharp" (5 = strongest sharpening)
"sharp" only helps when the game renders below 1280x800 (lower the in-game resolution). For 2D/pixel-art games use scaling_filter "pixel" (optionally scaling_mode "integer"), never "sharp"."""
SCALING_MODES = {"auto", "integer", "fit", "stretch", "fill"}
SCALING_FILTERS = {"linear", "pixel", "sharp"}


def _normalize_to_menu(settings: dict) -> dict:
    """Map old-style "fsr" to the menu's scaling_filter and drop values the Deck menu doesn't have."""
    out = dict(settings)
    fsr = out.pop("fsr", None)
    if fsr is True and "scaling_filter" not in out:
        out["scaling_filter"] = "sharp"
    if "scaling_filter" in out and str(out["scaling_filter"]).lower() not in SCALING_FILTERS:
        out.pop("scaling_filter")
    elif "scaling_filter" in out:
        out["scaling_filter"] = str(out["scaling_filter"]).lower()
    if "scaling_mode" in out and str(out["scaling_mode"]).lower() not in SCALING_MODES:
        out.pop("scaling_mode")
    elif "scaling_mode" in out:
        out["scaling_mode"] = str(out["scaling_mode"]).lower()
    if "sharpness" in out:
        try:
            out["sharpness"] = max(0, min(5, int(out["sharpness"])))
        except (TypeError, ValueError):
            out.pop("sharpness")
    return out


# Thresholds the model is told about but doesn't reliably follow — enforced in code instead
TEMP_HOT_C = 80
FAST_DRAIN_PCT_PER_HOUR = 50
GPU_BOTTLENECK_PCT = 90
GPU_IDLE_PCT = 60


def _enforce_rules(adjustments: dict, current: dict, stats: dict) -> tuple[dict, list[str]]:
    """Keep only adjustments the session metrics actually justify. Returns (kept, dropped reasons)."""
    temp = stats.get("temp_c_avg")
    gpu = stats.get("gpu_busy_avg")
    drain = stats.get("battery_drain_pct")
    minutes = stats.get("session_duration_min") or 0
    fps_avg, fps_min = stats.get("fps_avg"), stats.get("fps_min")
    limit = current.get("fps_limit")

    hot = temp is not None and temp > TEMP_HOT_C
    fast_drain = drain is not None and minutes >= 10 and drain / minutes * 60 > FAST_DRAIN_PCT_PER_HOUR
    bottleneck = gpu is not None and gpu > GPU_BOTTLENECK_PCT
    missing_target = bool(fps_avg and limit) and fps_avg < limit * 0.85
    stutter = bool(fps_avg and fps_min) and fps_min < fps_avg * 0.6
    # holding target with no heat/drain/GPU pressure: a lone fps_min dip (loading screen) isn't worth
    # cutting fps or image quality over, so it overrides the stutter/missing-target triggers
    smooth = bool(fps_avg) and fps_avg >= (limit or 60) * 0.95 and not (hot or fast_drain or bottleneck)
    headroom = bool(fps_avg and limit) and fps_avg > limit * 0.98 and gpu is not None and gpu < GPU_IDLE_PCT

    def direction(key, new):
        old = current.get(key)
        try:
            return (float(new) > float(old)) - (float(new) < float(old))
        except (TypeError, ValueError):
            return None  # no current value to compare against

    kept, dropped = {}, []
    for key, new in adjustments.items():
        d = direction(key, new) if key in ("gpu_clock", "fps_limit") else None
        if key == "gpu_clock" and d == -1:
            ok = hot or fast_drain
        elif key == "gpu_clock" and d == 1:
            ok = bottleneck and not hot
        elif key == "fps_limit" and d == -1:
            ok = (hot or fast_drain or bottleneck or missing_target or stutter) and not smooth
        elif key == "fps_limit" and d == 1:
            ok = headroom
        elif key == "fps_limit" and d is None:
            ok = not smooth  # adding a cap where none was set
        elif (key == "half_rate_shading" and new is True and not current.get(key)) or (
                key == "scaling_filter" and new == "sharp" and current.get(key) != "sharp"):
            ok = (hot or fast_drain or bottleneck or missing_target or stutter) and not smooth
        else:
            ok = True
        if ok:
            kept[key] = new
        else:
            dropped.append(f"{key} {current.get(key)}->{new}")
    return kept, dropped


def analyze_session(app_id: str, game_name: str, current_settings: dict,
                    session_stats: dict, sharedeck_data: dict = None,
                    session_history: list = None, settings_are_live: bool = False) -> dict:
    sd_context = ""
    if sharedeck_data and sharedeck_data.get("report_count"):
        sd_context = f"ShareDeck community ({sharedeck_data['report_count']} reports): {json.dumps(sharedeck_data)}"

    history_context = ""
    if session_history and len(session_history) > 1:
        past = session_history[:-1][-5:]
        history_lines = [
            f"- GPU avg:{s.get('gpu_busy_avg')}% power:{s.get('power_watts_avg')}W "
            f"temp:{s.get('temp_c_avg')}°C fps_avg:{s.get('fps_avg')} "
            f"battery_drain:{s.get('battery_drain_pct')}% duration:{s.get('session_duration_min')}min"
            + (f" settings:{json.dumps(_normalize_to_menu(s['settings_used']))}" if s.get("settings_used") else "")
            for s in past
        ]
        history_context = (
            f"Past {len(past)} session(s) (oldest first, most recent session is "
            f"the one being analyzed below):\n" + "\n".join(history_lines) +
            "\n\nUse this trend to judge if past adjustments actually helped — don't repeat a change "
            "that already happened and didn't fix the problem; if the same issue persists across "
            "multiple sessions, be more confident, not less.\n"
        )

    current_settings = _normalize_to_menu(current_settings)
    settings_label = (
        "Settings the user actually ran this session (read from the Deck; the user sets them by hand)"
        if settings_are_live else "Last recommended settings (what the user actually ran is unknown)"
    )
    session_stats = {k: v for k, v in session_stats.items() if k != "settings_used"}
    fps_rules = ""
    if session_stats.get("fps_avg") is not None:
        fps_rules = f"""- fps_avg vs fps_limit: if fps_avg < fps_limit * 0.85, game can't hit target — lower fps_limit or set scaling_filter "sharp"
- fps_avg > fps_limit * 0.98 and GPU avg < 60% = fps_limit too conservative, could raise it
- fps_min far below fps_avg = stuttering, lower fps_limit, set scaling_filter "sharp", or enable half_rate_shading
"""

    prompt = f"""You are a Steam Deck optimization expert analyzing a gameplay session.

Game: {game_name}
{settings_label}: {json.dumps(current_settings)}
Session performance: {json.dumps(session_stats)}
{history_context}
{sd_context}

{STEAM_MENU_OPTIONS}

Rules:
- TDP is managed by a separate measurement-based learner. NEVER include "tdp" in adjustments; treat it as fixed.
- GPU avg > 90% = GPU bottlenecked, lower graphics load (scaling_filter "sharp", half_rate_shading, fps_limit)
- Temp avg > 80°C = overheating, lower gpu_clock or fps_limit
- Battery drain > 50% in < 60 min = poor battery life, lower fps_limit or gpu_clock
- If ShareDeck data available, prefer their tested values
{fps_rules}
Output ONLY valid JSON:
{{
  "adjustments": {{only include fields that should change, e.g. "fps_limit": 30, "scaling_filter": "sharp"}},
  "recommendation": "<1-2 sentences using the Steam menu names above (e.g. Scaling Filter: Sharp), explaining what to change and why>",
  "confidence": <0.0-1.0>
}}"""

    try:
        resp = post_json(OLLAMA_URL, {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 200},
        }, timeout=30)
        raw = resp.get("response", "")
        json_match = raw[raw.find("{"):raw.rfind("}") + 1]
        if json_match:
            result = json.loads(json_match)
            # TDP belongs to the TDPLearner (measured); drop it even if the model ignores the prompt
            if isinstance(result.get("adjustments"), dict):
                result["adjustments"] = _normalize_to_menu(result["adjustments"])
            if isinstance(result.get("adjustments"), dict) and result["adjustments"].pop("tdp", None) is not None:
                logger.info(f"Dropped AI TDP suggestion for '{game_name}' (learner owns TDP)")
            if isinstance(result.get("adjustments"), dict) and result["adjustments"]:
                kept, dropped = _enforce_rules(result["adjustments"], current_settings, session_stats)
                if dropped:
                    logger.info(f"Dropped unjustified AI adjustments for '{game_name}': {dropped}")
                    result["adjustments"] = kept
                    if not kept:
                        result["recommendation"] = (
                            f"No change: AI suggested {', '.join(dropped)}, but the session metrics don't "
                            f"justify it (temp avg {session_stats.get('temp_c_avg')}°C, "
                            f"GPU avg {session_stats.get('gpu_busy_avg')}%, "
                            f"battery -{session_stats.get('battery_drain_pct')}% in "
                            f"{session_stats.get('session_duration_min')}min)."
                        )
            logger.info(f"AI session analysis for '{game_name}': {result}")
            return result
    except Exception as e:
        logger.warning(f"AI session analysis failed for '{game_name}': {e}")

    return {}
