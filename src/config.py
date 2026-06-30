#!/usr/bin/env python3
"""Configuration management for deck-optimizer."""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".config" / "deck-optimizer"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "deck_host": "deck@steamdeck.local",
    "deck_steamapps": "~/.local/share/Steam/steamapps",
    "deck_profiles_path": "~/.config/deck-optimizer/profiles.json",
    "discord_webhook_file": str(CONFIG_DIR / "discord-webhook"),
    "ollama_url": "http://localhost:11434/api/generate",
    "ollama_model": "qwen2.5:14b",
    "tdp_min": 4,
    "tdp_max": 15,
    "gpu_clock_min": 200,
    "gpu_clock_max": 1600,
    "display_hz": 60,
    "display_model": "lcd",
}


def load_config() -> dict:
    config = DEFAULTS.copy()
    if CONFIG_FILE.exists():
        try:
            user_config = json.loads(CONFIG_FILE.read_text())
            config.update(user_config)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"Invalid config file: {e}")
    return config


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


def get_webhook_url(config: dict) -> Optional[str]:
    webhook_file = Path(config["discord_webhook_file"])
    if webhook_file.exists():
        return webhook_file.read_text().strip()
    return None


def setup_interactive() -> dict:
    print("=== deck-optimizer setup ===\n")
    config = load_config()

    deck_host = input(f"Deck SSH host [{config['deck_host']}]: ").strip()
    if deck_host:
        config["deck_host"] = deck_host

    webhook = input("Discord webhook URL (blank to skip): ").strip()
    if webhook:
        webhook_file = Path(config["discord_webhook_file"])
        webhook_file.parent.mkdir(parents=True, exist_ok=True)
        webhook_file.write_text(webhook)
        webhook_file.chmod(0o600)
        print(f"  Saved to {webhook_file}")

    display = input(f"Display model (lcd/oled) [{config['display_model']}]: ").strip().lower()
    if display in ("lcd", "oled"):
        config["display_model"] = display
        config["display_hz"] = 90 if display == "oled" else 60

    try:
        import subprocess
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
        lines = [l.strip() for l in result.stdout.strip().splitlines()[1:] if l.strip()]
        models = [l.split()[0] for l in lines if l]
    except Exception:
        models = []

    if models:
        print("Available Ollama models:")
        for i, m in enumerate(models, 1):
            print(f"  {i}) {m}")
        choice = input(f"Ollama model (number or name) [{config['ollama_model']}]: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(models):
            config["ollama_model"] = models[int(choice) - 1]
        elif choice:
            config["ollama_model"] = choice
    else:
        ollama_model = input(f"Ollama model [{config['ollama_model']}]: ").strip()
        if ollama_model:
            config["ollama_model"] = ollama_model

    save_config(config)
    print(f"\nConfig saved to {CONFIG_FILE}")
    return config


if __name__ == "__main__":
    setup_interactive()
