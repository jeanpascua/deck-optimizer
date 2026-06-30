import json
import logging
import os
from dataclasses import dataclass, asdict, fields
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".config" / "deck-optimizer"
PROFILES_PATH = CONFIG_DIR / "profiles.json"

_KNOWN_FIELDS = None


@dataclass
class GameProfile:
    app_id: str
    game_name: str
    learned_tdp: Optional[float]
    session_count: int
    confidence: float
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


def _known_fields() -> set:
    global _KNOWN_FIELDS
    if _KNOWN_FIELDS is None:
        _KNOWN_FIELDS = {f.name for f in fields(GameProfile)}
    return _KNOWN_FIELDS


def _load_profile(data: dict) -> GameProfile:
    return GameProfile(**{k: v for k, v in data.items() if k in _known_fields()})


class ProfileStore:
    def __init__(self):
        self._data: dict[str, GameProfile] = {}
        self._load()

    def _load(self) -> None:
        if not PROFILES_PATH.exists():
            return
        try:
            raw = json.loads(PROFILES_PATH.read_text())
            self._data = {k: _load_profile(v) for k, v in raw.items()}
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"Failed to load profiles: {e}")

    def save(self) -> None:
        PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({k: asdict(v) for k, v in self._data.items()}, indent=2)
        tmp = PROFILES_PATH.with_suffix(".tmp")
        tmp.write_text(payload)
        os.replace(tmp, PROFILES_PATH)
        logger.debug(f"Saved {len(self._data)} profiles")

    def get(self, app_id: str) -> Optional[GameProfile]:
        return self._data.get(app_id)

    def set(self, app_id: str, profile: GameProfile) -> None:
        self._data[app_id] = profile

    def all(self) -> dict[str, GameProfile]:
        return self._data
