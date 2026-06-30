#!/usr/bin/env python3
"""Persist session performance data per game."""

import json
import logging
import os
from dataclasses import asdict
from pathlib import Path

logger = logging.getLogger(__name__)

SESSIONS_DIR = Path.home() / ".local" / "share" / "deck-optimizer" / "sessions"
MAX_SESSIONS = 10


def save_session(app_id: str, game_name: str, stats) -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    filepath = SESSIONS_DIR / f"{app_id}.json"

    data = {"app_id": app_id, "game_name": game_name, "sessions": []}
    if filepath.exists():
        try:
            data = json.loads(filepath.read_text())
        except (json.JSONDecodeError, TypeError):
            pass

    data["sessions"].append(asdict(stats))
    data["sessions"] = data["sessions"][-MAX_SESSIONS:]

    tmp = filepath.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, filepath)
    logger.info(f"Saved session for '{game_name}' ({len(data['sessions'])} stored)")


def load_sessions(app_id: str) -> list[dict]:
    filepath = SESSIONS_DIR / f"{app_id}.json"
    if not filepath.exists():
        return []
    try:
        data = json.loads(filepath.read_text())
        return data.get("sessions", [])
    except (json.JSONDecodeError, TypeError):
        return []


def load_all_sessions() -> dict[str, list[dict]]:
    result = {}
    if not SESSIONS_DIR.exists():
        return result
    for filepath in SESSIONS_DIR.glob("*.json"):
        app_id = filepath.stem
        try:
            data = json.loads(filepath.read_text())
            result[app_id] = data.get("sessions", [])
        except (json.JSONDecodeError, TypeError):
            continue
    return result
