import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".config" / "deck-optimizer"
PROFILES_PATH = CONFIG_DIR / "profiles.json"


@dataclass
class GameProfile:
    app_id: str
    game_name: str
    learned_tdp: Optional[float]
    session_count: int
    confidence: float  # 0.0 - 1.0
    target_fps: int = 40
    gpu_clock: Optional[int] = None
    fsr: Optional[bool] = None
    graphics_preset: Optional[str] = None
    resolution: Optional[str] = None
    shadows: Optional[str] = None
    antialiasing: Optional[str] = None
    textures: Optional[str] = None
    half_rate_shading: Optional[bool] = None
    allow_tearing: Optional[bool] = None
    disable_frame_limit: Optional[bool] = None
    scaling_mode: Optional[str] = None
    sharpness: Optional[int] = None
    scaling_filter: Optional[str] = None
    proton: Optional[str] = None
    settings_source: Optional[str] = None
    last_session_gpu_avg: Optional[float] = None
    last_session_power_avg: Optional[float] = None
    last_session_temp_avg: Optional[float] = None
    last_session_battery_drain: Optional[int] = None
    last_session_duration_min: Optional[float] = None


def load_profiles() -> dict[str, GameProfile]:
    if not PROFILES_PATH.exists():
        return {}
    try:
        with open(PROFILES_PATH) as f:
            data = json.load(f)
        return {k: GameProfile(**v) for k, v in data.items()}
    except (json.JSONDecodeError, TypeError) as e:
        logger.error(f"Failed to load profiles: {e}")
        return {}


def save_profiles(profiles: dict[str, GameProfile]) -> None:
    PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PROFILES_PATH, "w") as f:
        json.dump({k: asdict(v) for k, v in profiles.items()}, f, indent=2)
    logger.debug(f"Saved {len(profiles)} profiles")
