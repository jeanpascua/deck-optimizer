#!/usr/bin/env python3
"""Run optimizer on PC, sync profiles to Steam Deck."""

import json
import logging
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from optimizer.optimize import optimize_game
from config import load_config
from profiles import GameProfile, load_profiles, save_profiles

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_config = load_config()
DECK_HOST = _config["deck_host"]
DECK_STEAMAPPS = _config["deck_steamapps"]
DECK_PROFILES = _config["deck_profiles_path"]


def get_deck_games() -> list[dict]:
    result = subprocess.run(
        ["ssh", DECK_HOST, f'for f in {DECK_STEAMAPPS}/appmanifest_*.acf; do '
         f'id=$(grep -oP \'"appid"\\s+"\\K[0-9]+\' "$f"); '
         f'name=$(sed -n \'s/.*"name"\\s*"\\([^"]*\\)".*/\\1/p\' "$f"); '
         f'echo "$id|$name"; done'],
        capture_output=True, text=True, timeout=15,
    )
    games = []
    for line in result.stdout.strip().splitlines():
        if "|" in line:
            app_id, name = line.split("|", 1)
            if name and not name.startswith("Steam Linux Runtime") and not name.startswith("Proton") and name != "Steamworks Common Redistributables":
                games.append({"app_id": app_id, "name": name})
    return games


def sync_profiles_to_deck(profiles: dict):
    data = json.dumps({k: v.__dict__ if hasattr(v, '__dict__') else v for k, v in profiles.items()}, indent=2, default=str)
    tmp = Path("/tmp/deck-optimizer-profiles.json")
    tmp.write_text(data)
    subprocess.run(
        ["scp", str(tmp), f"{DECK_HOST}:{DECK_PROFILES}"],
        timeout=10,
    )
    tmp.unlink()
    logger.info(f"Synced {len(profiles)} profiles to Deck")


def main():
    logger.info("Fetching game list from Deck...")
    games = get_deck_games()
    logger.info(f"Found {len(games)} games")

    profiles = load_profiles()

    for game in games:
        app_id = game["app_id"]
        name = game["name"]
        logger.info(f"Optimizing: {name} ({app_id})")

        settings = optimize_game(app_id, name, profiles)
        method = settings.get("method", "none")

        profile = profiles.get(app_id)
        if profile is None:
            profile = GameProfile(
                app_id=app_id,
                game_name=name,
                learned_tdp=None,
                session_count=0,
                confidence=0.0,
            )
            profiles[app_id] = profile

        for field in ["tdp", "gpu_clock", "fsr", "graphics_preset", "resolution",
                       "shadows", "antialiasing", "textures", "half_rate_shading",
                       "allow_tearing", "disable_frame_limit", "scaling_mode",
                       "scaling_filter", "proton"]:
            val = settings.get(field)
            if val is not None:
                if field == "tdp" and isinstance(val, str):
                    try:
                        val = int(val.split("-")[0])
                    except ValueError:
                        continue
                    profile.learned_tdp = float(val)
                elif field == "tdp":
                    profile.learned_tdp = float(val)
                else:
                    setattr(profile, field, val)

        if settings.get("fps_limit"):
            try:
                profile.target_fps = int(settings["fps_limit"])
            except (ValueError, TypeError):
                pass

        profile.settings_source = method
        icon = {"community": "✅", "ai": "🤖", "none": "❓"}.get(method, "?")
        print(f"  {icon} {name}: TDP={profile.learned_tdp}W FPS={profile.target_fps} FSR={profile.fsr} Preset={profile.graphics_preset}")

        time.sleep(2)

    save_profiles(profiles)
    logger.info("Syncing profiles to Deck...")
    sync_profiles_to_deck(profiles)
    logger.info("Done!")

    subprocess.run(["ssh", DECK_HOST, "systemctl --user restart deck-optimizer"], timeout=10)
    logger.info("Deck service restarted")


if __name__ == "__main__":
    main()
