#!/usr/bin/env python3
import json
import logging
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from fps_monitor import SAMPLE_INTERVAL
from game_detector import get_active_game
from learner import TDPLearner, CONFIDENCE_PER_SESSION
from profiles import GameProfile, load_profiles, save_profiles
from tdp_controller import MAX_TDP, set_tdp, clear_active_tdp, set_gpu_clock, clear_gpu_clock, set_fps_limit, clear_fps_limit
try:
    from optimizer.scraper import get_community_settings
    from optimizer.ai_predict import predict_settings
    HAS_OPTIMIZER = True
except ImportError:
    HAS_OPTIMIZER = False

WEBHOOK_FILE = Path.home() / ".config" / "cron-alerts" / "discord-webhook"
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
    learner: Optional[TDPLearner] = None

    while True:
        result = get_active_game()

        if result is None:
            if current_app_id is not None:
                _on_game_exit(current_app_id, learner, profiles)
                current_app_id = None
                learner = None
        else:
            app_id, game_name = result

            if app_id != current_app_id:
                if current_app_id is not None:
                    _on_game_exit(current_app_id, learner, profiles)

                current_app_id = app_id
                learner = _on_game_launch(app_id, game_name, profiles)
            elif learner is not None:
                learner.tick()

        time.sleep(POLL_INTERVAL)


def _on_game_launch(
    app_id: str, game_name: str, profiles: dict[str, GameProfile]
) -> TDPLearner:
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

    if profile.learned_tdp is not None:
        logger.info(
            f"Loaded profile for '{game_name}': {profile.learned_tdp}W "
            f"(confidence={profile.confidence:.0%}, sessions={profile.session_count})"
        )
        initial_tdp = profile.learned_tdp
    else:
        initial_tdp = _get_initial_settings(app_id, game_name, profile, profiles)

    if profile.gpu_clock:
        set_gpu_clock(int(profile.gpu_clock))
    if profile.target_fps:
        set_fps_limit(profile.target_fps)

    _notify_discord(game_name, profile)
    return TDPLearner(initial_tdp=initial_tdp)


def _notify_discord(game_name: str, profile: GameProfile) -> None:
    if not WEBHOOK_FILE.exists():
        return
    try:
        webhook = WEBHOOK_FILE.read_text().strip()
        source = profile.settings_source or "learned"
        icon = {"community": "✅", "ai": "🤖", "learned": "📊"}.get(source, "🎮")

        lines = [f"🎮 **Now Playing: {game_name}** ({icon} {source})"]
        if profile.learned_tdp:
            lines.append(f"TDP: **{profile.learned_tdp}W**")
        if profile.target_fps:
            lines.append(f"FPS: **{profile.target_fps}**")
        if profile.graphics_preset:
            lines.append(f"Preset: **{profile.graphics_preset}**")
        if profile.fsr is not None:
            lines.append(f"FSR: **{'on' if profile.fsr else 'off'}**")
        if profile.resolution:
            lines.append(f"Res: **{profile.resolution}**")
        if profile.shadows:
            lines.append(f"Shadows: **{profile.shadows}**")
        if profile.antialiasing:
            lines.append(f"AA: **{profile.antialiasing}**")
        if profile.textures:
            lines.append(f"Textures: **{profile.textures}**")
        if profile.confidence > 0:
            lines.append(f"Confidence: **{profile.confidence:.0%}**")

        msg = " | ".join(lines)
        data = json.dumps({"content": msg}).encode()
        req = urllib.request.Request(webhook, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
        logger.info(f"Discord notified for '{game_name}'")
    except Exception as e:
        logger.warning(f"Discord notification failed: {e}")


def _get_initial_settings(
    app_id: str, game_name: str, profile: GameProfile, profiles: dict[str, GameProfile]
) -> Optional[float]:
    if not HAS_OPTIMIZER:
        logger.info(f"No optimizer module — starting '{game_name}' at {MAX_TDP}W")
        return None
    logger.info(f"New game '{game_name}' — checking community settings...")
    community = get_community_settings(game_name)

    if community and community.get("tdp"):
        tdp = community["tdp"]
        profile.settings_source = "community"
        _apply_settings(profile, community)
        logger.info(f"Community settings for '{game_name}': starting at {tdp}W")
        save_profiles(profiles)
        return float(tdp)

    logger.info(f"No community data — AI predicting for '{game_name}'...")
    try:
        ai = predict_settings(app_id, game_name, profiles)
        if ai and ai.get("tdp"):
            tdp = ai["tdp"]
            if isinstance(tdp, str):
                tdp = int(tdp.split("-")[0])
            profile.settings_source = "ai"
            _apply_settings(profile, ai)
            logger.info(f"AI predicted for '{game_name}': starting at {tdp}W")
            save_profiles(profiles)
            return float(tdp)
    except Exception as e:
        logger.warning(f"AI prediction failed: {e}")

    logger.info(f"No data for '{game_name}' — starting at {MAX_TDP}W")
    return None


def _apply_settings(profile: GameProfile, settings: dict) -> None:
    for field in ["gpu_clock", "fsr", "graphics_preset", "resolution",
                   "shadows", "antialiasing", "textures"]:
        val = settings.get(field)
        if val is not None:
            setattr(profile, field, val)
    if settings.get("fps_limit"):
        try:
            profile.target_fps = int(settings["fps_limit"])
        except (ValueError, TypeError):
            pass


def _on_game_exit(
    app_id: str,
    learner: Optional[TDPLearner],
    profiles: dict[str, GameProfile],
) -> None:
    if learner is None:
        return

    learned_tdp = learner.session_ended()
    existing = profiles.get(app_id)

    if existing is None:
        return

    existing.learned_tdp = learned_tdp
    existing.session_count += 1
    existing.confidence = min(1.0, existing.session_count * CONFIDENCE_PER_SESSION)

    save_profiles(profiles)
    logger.info(
        f"Saved profile for '{existing.game_name}': "
        f"{learned_tdp}W confidence={existing.confidence:.0%}"
    )
    set_tdp(MAX_TDP)
    clear_gpu_clock()
    clear_fps_limit()
    clear_active_tdp()


if __name__ == "__main__":
    main()
