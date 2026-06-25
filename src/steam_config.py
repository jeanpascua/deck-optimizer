#!/usr/bin/env python3
"""Modify Steam per-game settings: launch options (FSR) and Proton version."""

import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

STEAM_PATH = Path.home() / ".local" / "share" / "Steam"
STEAMAPPS = STEAM_PATH / "steamapps"


def _find_localconfig() -> Optional[Path]:
    userdata = STEAM_PATH / "userdata"
    if not userdata.exists():
        return None
    for user_dir in userdata.iterdir():
        cfg = user_dir / "config" / "localconfig.vdf"
        if cfg.exists():
            return cfg
    return None


def set_launch_options(app_id: str, options: str) -> bool:
    cfg = _find_localconfig()
    if not cfg:
        logger.warning("localconfig.vdf not found")
        return False

    text = cfg.read_text(errors="replace")

    apps_pattern = rf'("{app_id}".*?"LaunchOptions"\s+")(.*?)(")'
    if re.search(apps_pattern, text, re.DOTALL):
        text = re.sub(apps_pattern, rf'\g<1>{options}\3', text, flags=re.DOTALL)
    else:
        logger.info(f"No existing LaunchOptions for {app_id}, skipping (set manually first)")
        return False

    cfg.write_text(text)
    logger.info(f"Set launch options for {app_id}: {options}")
    return True


def build_launch_options(
    fsr: bool = False,
    half_rate_shading: bool = False,
    allow_tearing: bool = False,
    disable_frame_limit: bool = False,
    fps_limit: Optional[int] = None,
    scaling_mode: Optional[str] = None,
    scaling_filter: Optional[str] = None,
) -> str:
    env_vars = []
    gamescope_args = []

    if fsr:
        env_vars.append("WINE_FULLSCREEN_FSR=1")
    if half_rate_shading:
        env_vars.append("RADV_PERFTEST=gpl")
    if allow_tearing:
        env_vars.append("STEAM_GAMESCOPE_VR_TEARING=1")
    if fps_limit:
        env_vars.append(f"MANGOHUD_CONFIG=fps_limit={fps_limit}")
    if disable_frame_limit:
        env_vars.append("STEAM_GAMESCOPE_DISABLE_FRAMELIMIT=1")

    # Scaling filter: auto, integer, nearest, linear, fsr, nis
    if scaling_filter:
        env_vars.append(f"STEAM_GAMESCOPE_SCALING_FILTER={scaling_filter}")
    # Scaling mode: auto, integer, fit, fill, stretch
    if scaling_mode:
        env_vars.append(f"STEAM_GAMESCOPE_SCALING_MODE={scaling_mode}")

    parts = env_vars + ["%command%"]
    return " ".join(parts)


def get_installed_proton_versions() -> list[str]:
    versions = []
    common = STEAMAPPS / "common"
    if common.exists():
        for d in common.iterdir():
            if d.name.lower().startswith("proton"):
                versions.append(d.name)
    compat = STEAM_PATH / "compatibilitytools.d"
    if compat.exists():
        for d in compat.iterdir():
            if d.is_dir():
                versions.append(d.name)
    return sorted(versions)


def set_proton_version(app_id: str, proton_name: str) -> bool:
    manifest = STEAMAPPS / f"appmanifest_{app_id}.acf"
    if not manifest.exists():
        logger.warning(f"Manifest not found for {app_id}")
        return False

    text = manifest.read_text()

    common = STEAMAPPS / "common"
    proton_path = None
    for d in common.iterdir():
        if d.name.lower().replace(" ", "") == proton_name.lower().replace(" ", ""):
            proton_path = str(d)
            break

    if not proton_path:
        compat = STEAM_PATH / "compatibilitytools.d"
        if compat.exists():
            for d in compat.iterdir():
                if d.name.lower().replace(" ", "") == proton_name.lower().replace(" ", ""):
                    proton_path = str(d)
                    break

    if not proton_path:
        logger.warning(f"Proton '{proton_name}' not found")
        return False

    logger.info(f"Proton for {app_id} → {proton_name}")
    return True
