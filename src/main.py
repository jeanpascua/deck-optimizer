#!/usr/bin/env python3
import logging
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from fps_monitor import SAMPLE_INTERVAL
from game_detector import get_active_game
from learner import TDPLearner, CONFIDENCE_PER_SESSION
from profiles import GameProfile, load_profiles, save_profiles
from tdp_controller import MAX_TDP, set_tdp, clear_active_tdp

LOG_PATH = Path.home() / ".local" / "share" / "deck-auto-tdp" / "service.log"
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
    logger.info("deck-auto-tdp started")

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
        logger.info(f"No profile for '{game_name}' — starting at {MAX_TDP}W")
        initial_tdp = None

    return TDPLearner(initial_tdp=initial_tdp)


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
    clear_active_tdp()


if __name__ == "__main__":
    main()
