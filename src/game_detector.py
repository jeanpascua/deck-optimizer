import glob
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

STEAMAPPS_PATH = Path.home() / ".local" / "share" / "Steam" / "steamapps"


def get_active_game() -> Optional[tuple[str, str]]:
    """Scan /proc for a running Steam game. Returns (app_id, game_name) or None."""
    for environ_path in glob.glob("/proc/*/environ"):
        try:
            with open(environ_path, "rb") as f:
                raw = f.read()
            env = {}
            for entry in raw.split(b"\x00"):
                if b"=" in entry:
                    k, v = entry.split(b"=", 1)
                    env[k.decode(errors="ignore")] = v.decode(errors="ignore")

            app_id = env.get("SteamAppId", "0").strip()
            if app_id and app_id != "0":
                return app_id, _get_game_name(app_id)
        except (PermissionError, FileNotFoundError, ValueError):
            continue
    return None


def _get_game_name(app_id: str) -> str:
    manifest = STEAMAPPS_PATH / f"appmanifest_{app_id}.acf"
    if manifest.exists():
        match = re.search(r'"name"\s+"([^"]+)"', manifest.read_text())
        if match:
            return match.group(1)
    return f"App_{app_id}"
