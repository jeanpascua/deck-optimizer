#!/usr/bin/env python3
import json
import logging
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from fps_monitor import SAMPLE_INTERVAL
from game_detector import get_active_game
from profiles import GameProfile, ProfileStore, apply_settings, profile_to_settings
from perf_monitor import SessionMonitor
from session_store import save_session, load_sessions
from config import load_config

try:
    from optimizer.scraper import get_community_settings
    from optimizer.ai_predict import predict_settings, analyze_session
    HAS_OPTIMIZER = True
    _OPTIMIZER_IMPORT_ERROR = None
except ImportError as e:
    HAS_OPTIMIZER = False
    _OPTIMIZER_IMPORT_ERROR = e

try:
    from learner import TDPLearner
    HAS_LEARNER = True
except ImportError:
    HAS_LEARNER = False

_config = load_config()
WEBHOOK_FILE = Path(_config["discord_webhook_file"]).expanduser()
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

_active_monitor: Optional[SessionMonitor] = None
_active_learner: Optional["TDPLearner"] = None


REQUIRED_CONFIRMATIONS = 2  # consecutive polls a detection must hold before it's trusted
REQUIRED_AI_CONFIRMATIONS = 2   # consecutive sessions an AI adjustment must repeat before auto-applying
AI_CONFIDENCE_FLOOR = 0.6       # below this, don't even count toward the streak


def main() -> None:
    global _active_monitor, _active_learner
    logger.info("deck-optimizer started")
    if not HAS_OPTIMIZER:
        logger.warning(f"AI/community optimizer disabled — import failed: {_OPTIMIZER_IMPORT_ERROR}")

    store = ProfileStore()
    current_app_id: Optional[str] = None
    pending_id: Optional[str] = None
    pending_name: str = ""
    pending_streak = 0

    while True:
        result = get_active_game()
        detected_id = result[0] if result else None
        detected_name = result[1] if result else ""

        if detected_id == pending_id:
            pending_streak += 1
        else:
            pending_id, pending_name, pending_streak = detected_id, detected_name, 1

        if pending_streak >= REQUIRED_CONFIRMATIONS and pending_id != current_app_id:
            if current_app_id is not None:
                _on_game_exit(current_app_id, store)
                _active_monitor = None
                _active_learner = None

            current_app_id = pending_id

            if current_app_id is not None:
                _on_game_launch(current_app_id, pending_name, store)
                _active_monitor = SessionMonitor()
                if HAS_LEARNER:
                    try:
                        profile = store.get(current_app_id)
                        _active_learner = TDPLearner(initial_tdp=profile.learned_tdp if profile else None)
                        logger.info(f"TDPLearner started at {profile.learned_tdp or 'MAX'}W")
                    except Exception as e:
                        logger.warning(f"TDPLearner init failed: {e}")
                        _active_learner = None
        elif detected_id == current_app_id and current_app_id is not None and _active_monitor is not None:
            _active_monitor.sample()
            if _active_learner is not None:
                _active_learner.tick()

        time.sleep(POLL_INTERVAL)


def _on_game_launch(app_id: str, game_name: str, store: ProfileStore) -> None:
    profile = store.get(app_id)
    if profile is None:
        profile = GameProfile(
            app_id=app_id,
            game_name=game_name,
            learned_tdp=None,
            session_count=0,
            confidence=0.0,
        )
        store.set(app_id, profile)

    threading.Thread(target=_launch_background, args=(app_id, game_name, profile, store), daemon=True).start()


def _launch_background(app_id: str, game_name: str, profile: GameProfile, store: ProfileStore) -> None:
    _notify_discord(game_name, profile)
    if profile.settings_source is None and HAS_OPTIMIZER:
        _fetch_settings(app_id, game_name, profile, store)


def _fetch_settings(app_id: str, game_name: str, profile: GameProfile, store: ProfileStore) -> None:
    logger.info(f"New game '{game_name}' — checking community settings...")
    # If the TDP learner already has real sessions, its measured TDP beats a lookup/guess
    keep_tdp = bool(load_sessions(app_id))
    community = get_community_settings(game_name, app_id=app_id)
    if keep_tdp and community:
        community.pop("tdp", None)

    useful_keys = [k for k in community if k not in ("source",) and community[k] is not None]
    if community and len(useful_keys) >= 3:
        profile.settings_source = "community"
        apply_settings(profile, community)
        logger.info(f"Community settings found for '{game_name}' ({len(useful_keys)} fields)")
        store.save()
        return

    logger.info(f"No community data — AI predicting for '{game_name}'...")
    try:
        ai = predict_settings(app_id, game_name, store.all(), session_history=load_sessions(app_id))
        if ai:
            if keep_tdp:
                ai.pop("tdp", None)
            profile.settings_source = "ai"
            apply_settings(profile, ai)
            logger.info(f"AI predicted settings for '{game_name}'")
            store.save()
    except Exception as e:
        logger.warning(f"AI prediction failed: {e}")


def _notify_discord(game_name: str, profile: GameProfile) -> None:
    if not WEBHOOK_FILE.exists():
        return
    try:
        webhook = WEBHOOK_FILE.read_text().strip()
        source = profile.settings_source or "no profile"
        source_label = {"community": "Community Tested ✅", "ai": "AI Predicted 🤖"}.get(source, "No Profile ❓")
        color = {"community": 0x2ECC71, "ai": 0x3498DB}.get(source, 0x95A5A6)

        fps = profile.target_fps or "—"
        tdp = f"{profile.learned_tdp}W" if profile.learned_tdp else "—"
        gpu = f"{profile.gpu_clock} MHz" if profile.gpu_clock else "—"
        scaling_filter = profile.scaling_filter or ("sharp" if profile.fsr else "linear")

        embed = {
            "title": f"🎮 {game_name}",
            "color": color,
            "fields": [
                {"name": "Frame Limit", "value": f"`{fps}`", "inline": True},
                {"name": "Disable Frame Limit", "value": f"`{'on' if profile.disable_frame_limit else 'off'}`", "inline": True},
                {"name": "Allow Tearing", "value": f"`{'on' if profile.allow_tearing else 'off'}`", "inline": True},
                {"name": "Half Rate Shading", "value": f"`{'on' if profile.half_rate_shading else 'off'}`", "inline": True},
                {"name": "TDP Limit", "value": f"`{tdp}`", "inline": True},
                {"name": "Manual GPU Clock", "value": f"`{gpu}`", "inline": True},
                {"name": "Scaling Mode", "value": f"`{profile.scaling_mode or 'auto'}`", "inline": True},
                {"name": "Scaling Filter", "value": f"`{scaling_filter}`" + (f" (sharpness `{profile.sharpness}`)" if profile.sharpness is not None else ""), "inline": True},
            ],
            "footer": {"text": f"Source: {source_label} • Sessions: {profile.session_count}"},
        }

        _send_discord(webhook, {"embeds": [embed]})
        logger.info(f"Discord notified for '{game_name}'")
    except Exception as e:
        logger.warning(f"Discord notification failed: {e}")


def _notify_discord_session_end(game_name: str, profile: GameProfile, stats) -> None:
    if not WEBHOOK_FILE.exists():
        return
    try:
        webhook = WEBHOOK_FILE.read_text().strip()

        fields = []
        if stats.gpu_busy_avg is not None:
            fields.append({"name": "GPU Busy", "value": f"`avg {stats.gpu_busy_avg}%` / `max {stats.gpu_busy_max}%`", "inline": True})
        if stats.power_watts_avg is not None:
            fields.append({"name": "Power Draw", "value": f"`avg {stats.power_watts_avg}W` / `max {stats.power_watts_max}W`", "inline": True})
        if stats.temp_c_avg is not None:
            fields.append({"name": "Temperature", "value": f"`avg {stats.temp_c_avg}°C` / `max {stats.temp_c_max}°C`", "inline": True})
        if stats.battery_drain_pct is not None:
            fields.append({"name": "Battery", "value": f"`{stats.battery_start_pct}%` → `{stats.battery_end_pct}%` (`-{stats.battery_drain_pct}%`)", "inline": True})
        if stats.fps_avg is not None:
            fields.append({"name": "FPS", "value": f"`avg {stats.fps_avg}` / `min {stats.fps_min}`", "inline": True})
        fields.append({"name": "Duration", "value": f"`{stats.session_duration_min} min`", "inline": True})
        fields.append({"name": "Samples", "value": f"`{stats.sample_count}`", "inline": True})

        embed = {
            "title": f"📊 Session End: {game_name}",
            "color": 0xE67E22,
            "fields": fields,
            "footer": {"text": f"Session #{profile.session_count}"},
        }

        _send_discord(webhook, {"embeds": [embed]})
        logger.info(f"Session stats sent for '{game_name}'")
    except Exception as e:
        logger.warning(f"Session Discord notification failed: {e}")


def _send_discord(webhook: str, payload_dict: dict) -> None:
    payload = json.dumps(payload_dict)
    subprocess.run(
        ["curl", "-fsS", "-X", "POST", webhook,
         "-H", "Content-Type: application/json",
         "-d", payload],
        capture_output=True, timeout=10,
    )


def _adjustment_direction(profile: GameProfile, adjustments: dict) -> dict:
    """Reduce an adjustments dict to per-field direction so two sessions recommending
    'lower TDP' compare equal even if the LLM picked slightly different numbers."""
    current_settings = profile_to_settings(profile)  # adjustment keys are tdp/fps_limit, not profile field names
    direction = {}
    for key, val in adjustments.items():
        current = current_settings.get(key)
        if (isinstance(val, (int, float)) and not isinstance(val, bool)
                and isinstance(current, (int, float)) and not isinstance(current, bool)):
            diff = val - current
            direction[key] = "up" if diff > 0 else "down" if diff < 0 else "same"
        else:
            direction[key] = val
    return direction


def _run_ai_analysis(app_id: str, profile: GameProfile, stats, store: ProfileStore) -> None:
    if not HAS_OPTIMIZER:
        return
    if stats.session_duration_min < 5:
        logger.info(f"Session too short ({stats.session_duration_min}min), skipping AI analysis")
        return

    current_settings = profile_to_settings(profile)
    try:
        result = analyze_session(
            app_id, profile.game_name, current_settings, asdict(stats),
            session_history=load_sessions(app_id),
        )
    except Exception as e:
        logger.warning(f"AI analysis failed for '{profile.game_name}': {e}")
        return

    if not result:
        return

    adjustments = result.get("adjustments", {})
    recommendation = result.get("recommendation", "")
    confidence = float(result.get("confidence", 0.0))

    applied = False
    if adjustments and confidence >= AI_CONFIDENCE_FLOOR:
        direction = _adjustment_direction(profile, adjustments)
        if direction == profile.pending_adjustment:
            profile.pending_streak += 1
        else:
            profile.pending_adjustment = direction
            profile.pending_streak = 1

        if profile.pending_streak >= REQUIRED_AI_CONFIRMATIONS:
            apply_settings(profile, adjustments)
            profile.settings_source = "ai_learned"
            profile.pending_adjustment = None
            profile.pending_streak = 0
            applied = True
            logger.info(
                f"AI auto-applied settings for '{profile.game_name}' "
                f"(confidence={confidence:.0%}, confirmed {REQUIRED_AI_CONFIRMATIONS}x): {adjustments}"
            )
        else:
            logger.info(
                f"AI suggests {adjustments} for '{profile.game_name}' "
                f"(confidence={confidence:.0%}, streak={profile.pending_streak}/{REQUIRED_AI_CONFIRMATIONS}) — waiting for repeat"
            )
        store.save()
    elif profile.pending_adjustment is not None:
        profile.pending_adjustment = None
        profile.pending_streak = 0
        store.save()

    # Skip "No change" verdicts; the session-end embed already covers those sessions
    if confidence >= 0.7 and recommendation and adjustments:
        _notify_discord_ai_recommendation(profile.game_name, recommendation, adjustments, confidence, applied)


def _notify_discord_ai_recommendation(
    game_name: str, recommendation: str, adjustments: dict, confidence: float, applied: bool
) -> None:
    if not WEBHOOK_FILE.exists():
        return
    try:
        webhook = WEBHOOK_FILE.read_text().strip()
        status = "Auto-applied ✅" if applied else "Suggestion 💡"
        adj_text = "\n".join(f"`{k}`: **{v}**" for k, v in adjustments.items()) if adjustments else "No changes needed"
        embed = {
            "title": f"🤖 AI Analysis: {game_name}",
            "color": 0x9B59B6 if applied else 0xF39C12,
            "description": recommendation,
            "fields": [
                {"name": "Adjustments", "value": adj_text, "inline": False},
                {"name": "Confidence", "value": f"`{confidence:.0%}`", "inline": True},
                {"name": "Status", "value": status, "inline": True},
            ],
        }
        _send_discord(webhook, {"embeds": [embed]})
        logger.info(f"AI recommendation sent for '{game_name}'")
    except Exception as e:
        logger.warning(f"AI recommendation Discord failed: {e}")


def _exit_background(app_id: str, profile: GameProfile, stats, store: ProfileStore) -> None:
    _notify_discord_session_end(profile.game_name, profile, stats)
    _run_ai_analysis(app_id, profile, stats, store)


def _on_game_exit(app_id: str, store: ProfileStore) -> None:
    global _active_monitor
    existing = store.get(app_id)
    if existing is None:
        return

    if _active_monitor is not None:
        if _active_learner is not None:
            learned_tdp = _active_learner.session_ended()
            existing.learned_tdp = learned_tdp
            logger.info(f"TDPLearner converged: {learned_tdp}W for '{existing.game_name}'")
        stats = _active_monitor.summarize()
        save_session(app_id, existing.game_name, stats)
        existing.last_session_gpu_avg = stats.gpu_busy_avg
        existing.last_session_power_avg = stats.power_watts_avg
        existing.last_session_temp_avg = stats.temp_c_avg
        existing.last_session_battery_drain = stats.battery_drain_pct
        existing.last_session_duration_min = stats.session_duration_min
        existing.session_count += 1
        store.save()
        logger.info(f"Session ended for '{existing.game_name}' (session #{existing.session_count})")
        threading.Thread(target=_exit_background, args=(app_id, existing, stats, store), daemon=True).start()
    else:
        existing.session_count += 1
        store.save()
        logger.info(f"Session ended for '{existing.game_name}' (no monitor)")


if __name__ == "__main__":
    main()
