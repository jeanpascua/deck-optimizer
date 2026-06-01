import json
import logging
import urllib.request
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CONFIG_PATH = Path.home() / ".config" / "deck-auto-tdp" / "config.json"


def _webhook_url() -> Optional[str]:
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f).get("discord_webhook")
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def notify_game_launch(
    game_name: str,
    learned_tdp: Optional[float],
    recommended_mode: Optional[str],
    confidence: float,
    session_count: int,
) -> None:
    url = _webhook_url()
    if not url:
        return

    if learned_tdp is None:
        description = "No profile yet — learning TDP this session."
    else:
        mode_str = "40fps / 40Hz" if recommended_mode == "battery" else "60fps / 60Hz"
        description = (
            f"⚡ TDP: **{learned_tdp}W** (auto-managed)\n"
            f"📺 Recommended: **{mode_str}**\n"
            f"📊 Confidence: {confidence:.0%} ({session_count} sessions)"
        )

    payload = json.dumps({
        "embeds": [{
            "title": f"🎮 {game_name}",
            "description": description,
            "color": 0x1a9fff,
        }]
    }).encode()

    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "deck-auto-tdp/1.0",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        logger.warning(f"Discord notify failed: {e}")
