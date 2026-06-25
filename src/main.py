#!/usr/bin/env python3
import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from fps_monitor import SAMPLE_INTERVAL
from game_detector import get_active_game
from profiles import GameProfile, load_profiles, save_profiles
from config import load_config

try:
    from optimizer.scraper import get_community_settings
    from optimizer.ai_predict import predict_settings
    HAS_OPTIMIZER = True
except ImportError:
    HAS_OPTIMIZER = False

_config = load_config()
WEBHOOK_FILE = Path(_config["discord_webhook_file"])
LOG_PATH = Path.home() / ".local" / "share" / "deck-optimizer" / "service.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
POLL_INTERVAL = SAMPLE_INTERVAL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, mode="a"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("deck-optimizer started")

    profiles = load_profiles()
    current_app_id: Optional[str] = None

    while True:
        result = get_active_game()

        if result is None:
            if current_app_id is not None:
                _on_game_exit(current_app_id, profiles)
                current_app_id = None
        else:
            app_id, game_name = result

            if app_id != current_app_id:
                if current_app_id is not None:
                    _on_game_exit(current_app_id, profiles)

                current_app_id = app_id
                _on_game_launch(app_id, game_name, profiles)

        time.sleep(POLL_INTERVAL)


def _on_game_launch(
    app_id: str, game_name: str, profiles: dict[str, GameProfile]
) -> None:
    profile = profiles.get(app_id)
    if profile is None:
        profile = GameProfile(
            app_id=app_id,
            game_name=game_name,
            learned_tdp=None,
            session_count=0,
            confidence=0.0,
        )
        profiles[app_id] = profile

    if profile.settings_source is None and HAS_OPTIMIZER:
        _fetch_settings(app_id, game_name, profile, profiles)

    _notify_discord(game_name, profile)


def _fetch_settings(
    app_id: str, game_name: str, profile: GameProfile, profiles: dict[str, GameProfile]
) -> None:
    logger.info(f"New game '{game_name}' — checking community settings...")
    community = get_community_settings(game_name)

    if community and len(community) > 2:
        profile.settings_source = "community"
        _apply_settings(profile, community)
        logger.info(f"Community settings found for '{game_name}'")
        save_profiles(profiles)
        return

    logger.info(f"No community data — AI predicting for '{game_name}'...")
    try:
        ai = predict_settings(app_id, game_name, profiles)
        if ai:
            profile.settings_source = "ai"
            _apply_settings(profile, ai)
            logger.info(f"AI predicted settings for '{game_name}'")
            save_profiles(profiles)
    except Exception as e:
        logger.warning(f"AI prediction failed: {e}")


def _apply_settings(profile: GameProfile, settings: dict) -> None:
    for field in ["gpu_clock", "fsr", "half_rate_shading", "allow_tearing",
                   "disable_frame_limit", "scaling_mode", "scaling_filter"]:
        val = settings.get(field)
        if val is not None:
            setattr(profile, field, val)
    if settings.get("tdp"):
        tdp = settings["tdp"]
        if isinstance(tdp, str):
            try:
                tdp = int(tdp.split("-")[0])
            except ValueError:
                return
        profile.learned_tdp = float(tdp)
    if settings.get("fps_limit"):
        try:
            profile.target_fps = int(settings["fps_limit"])
        except (ValueError, TypeError):
            pass


def _notify_discord(game_name: str, profile: GameProfile) -> None:
    if not WEBHOOK_FILE.exists():
        return
    try:
        webhook = WEBHOOK_FILE.read_text().strip()
        source = profile.settings_source or "no profile"
        source_label = {"community": "Community Tested ✅", "ai": "AI Predicted 🤖"}.get(source, "No Profile ❓")
        color = {"community": 0x2ECC71, "ai": 0x3498DB}.get(source, 0x95A5A6)

        fps = profile.target_fps or "—"
        tdp = f"{profile.learned_tdp}W" if profile.learned_tdp else "—"
        gpu = f"{profile.gpu_clock} MHz" if profile.gpu_clock else "—"
        scaling_filter = profile.scaling_filter or ("FSR" if profile.fsr else "—")

        embed = {
            "title": f"🎮 {game_name}",
            "color": color,
            "fields": [
                {"name": "Frame Limit", "value": f"`{fps}`", "inline": True},
                {"name": "Disable Frame Limit", "value": f"`{'on' if profile.disable_frame_limit else 'off'}`", "inline": True},
                {"name": "Allow Tearing", "value": f"`{'on' if profile.allow_tearing else 'off'}`", "inline": True},
                {"name": "Half Rate Shading", "value": f"`{'on' if profile.half_rate_shading else 'off'}`", "inline": True},
                {"name": "TDP Limit", "value": f"`{tdp}`", "inline": True},
                {"name": "Manual GPU Clock", "value": f"`{gpu}`", "inline": True},
                {"name": "Scaling Mode", "value": f"`{profile.scaling_mode or 'auto'}`", "inline": True},
                {"name": "Scaling Filter", "value": f"`{scaling_filter}`", "inline": True},
            ],
            "footer": {"text": f"Source: {source_label} • Sessions: {profile.session_count}"},
        }

        payload = json.dumps({"embeds": [embed]})
        subprocess.run(
            ["curl", "-fsS", "-X", "POST", webhook,
             "-H", "Content-Type: application/json",
             "-d", payload],
            capture_output=True, timeout=10,
        )
        logger.info(f"Discord notified for '{game_name}'")
    except Exception as e:
        logger.warning(f"Discord notification failed: {e}")


def _on_game_exit(
    app_id: str,
    profiles: dict[str, GameProfile],
) -> None:
    existing = profiles.get(app_id)
    if existing is None:
        return

    existing.session_count += 1
    save_profiles(profiles)
    logger.info(f"Session ended for '{existing.game_name}' (session #{existing.session_count})")


if __name__ == "__main__":
    main()
