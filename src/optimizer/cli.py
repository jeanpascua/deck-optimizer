#!/usr/bin/env python3
"""CLI for deck settings optimizer."""

import argparse
import json
import logging
import os
import sys
import requests

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from optimizer.optimize import get_installed_games, optimize_game, optimize_library, format_discord
from profiles import load_profiles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def post_discord(messages: list[str], webhook_url: str):
    for msg in messages:
        requests.post(webhook_url, json={"content": msg}, timeout=10)


def main():
    parser = argparse.ArgumentParser(description="Steam Deck game settings optimizer")
    parser.add_argument("--game", help="Optimize a single game by name")
    parser.add_argument("--app-id", help="Optimize a single game by Steam app ID")
    parser.add_argument("--library", action="store_true", help="Optimize all installed games")
    parser.add_argument("--discord", action="store_true", help="Post results to Discord")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    profiles = load_profiles()
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "")

    if args.game or args.app_id:
        app_id = args.app_id or "0"
        name = args.game or f"App_{app_id}"
        settings = optimize_game(app_id, name, profiles)
        settings["name"] = name

        if args.json:
            print(json.dumps(settings, indent=2))
        else:
            print(f"\n{'=' * 40}")
            print(f"  {name}")
            print(f"{'=' * 40}")
            for k, v in settings.items():
                if k not in ("source", "method"):
                    print(f"  {k}: {v}")
            print()

        if args.discord and webhook:
            msgs = format_discord({app_id: settings})
            post_discord(msgs, webhook)

    elif args.library:
        games = get_installed_games()
        if not games:
            print("No installed games found. Run this on your Steam Deck.")
            print("Or provide --game 'Game Name' to optimize a specific game.")
            return

        all_settings = optimize_library(games, profiles)

        if args.json:
            print(json.dumps(all_settings, indent=2))
        else:
            for app_id, s in all_settings.items():
                icon = {"community": "✅", "ai": "🤖", "none": "❓"}.get(s.get("method"), "?")
                print(f"{icon} {s.get('name', app_id)}: {s}")

        if args.discord and webhook:
            msgs = format_discord(all_settings)
            post_discord(msgs, webhook)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
