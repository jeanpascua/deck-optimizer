#!/usr/bin/env python3
"""CLI for deck settings optimizer."""

import argparse
import json
import logging
import os
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from optimizer.optimize import get_installed_games, optimize_game, optimize_library, format_discord
from optimizer.ai_predict import analyze_session
from optimizer.netutil import post_json
from profiles import ProfileStore, apply_settings, profile_to_settings
from session_store import load_sessions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def post_discord(messages: list[str], webhook_url: str):
    for msg in messages:
        post_json(webhook_url, {"content": msg}, timeout=10)


def main():
    parser = argparse.ArgumentParser(description="Steam Deck game settings optimizer")
    parser.add_argument("--game", help="Optimize a single game by name")
    parser.add_argument("--app-id", help="Optimize a single game by Steam app ID")
    parser.add_argument("--library", action="store_true", help="Optimize all installed games")
    parser.add_argument("--analyze", action="store_true",
                         help="Run AI analysis now using recorded play sessions for --app-id, "
                              "and apply the result immediately (bypasses the normal debounce)")
    parser.add_argument("--discord", action="store_true", help="Post results to Discord")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    store = ProfileStore()
    profiles = store.all()
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "")

    if args.analyze:
        if not args.app_id:
            parser.error("--analyze requires --app-id")

        profile = store.get(args.app_id)
        if profile is None:
            print(f"No profile for app_id {args.app_id} yet. Launch the game on the Deck at least once first.")
            return

        sessions = load_sessions(args.app_id)
        if not sessions:
            print(f"No play sessions recorded for '{profile.game_name}' yet. Play at least once first.")
            return

        # analyze_session treats the last entry of session_history as the session being analyzed
        current_settings = profile_to_settings(profile)
        result = analyze_session(args.app_id, profile.game_name, current_settings, sessions[-1], session_history=sessions)

        if not result:
            print("AI analysis returned nothing (Ollama unreachable or bad response).")
            return

        adjustments = result.get("adjustments", {})
        recommendation = result.get("recommendation", "")
        confidence = float(result.get("confidence", 0.0))

        print(f"\n{profile.game_name} — confidence {confidence:.0%}")
        if recommendation:
            print(recommendation)

        if not adjustments:
            print("\nNo changes recommended.")
            return

        before = current_settings  # already uses profile_to_settings' field naming (tdp, fps_limit, ...)
        print("\nApplying:")
        for k, v in adjustments.items():
            print(f"  {k}: {before.get(k, '?')} -> {v}")

        apply_settings(profile, adjustments)
        profile.settings_source = "ai_manual"
        profile.pending_adjustment = None
        profile.pending_streak = 0
        store.save()
        print("\nApplied.")

        if args.discord and webhook:
            msgs = format_discord({args.app_id: {"name": profile.game_name, "method": "ai", **adjustments}})
            post_discord(msgs, webhook)
        return

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
