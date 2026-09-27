#!/usr/bin/env python3
"""Read the Quick Access > Performance settings the user actually has set. Read-only: never changes them.

Steam pushes the menu values to gamescope as X root-window atoms; the manual GPU clock and
TDP limit live in amdgpu sysfs.
"""

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

GAMESCOPE_DISPLAY = ":0"
DRM_DEVICE = Path("/sys/class/drm/card0/device")

# gamescope enums -> the labels in the Steam menu
SCALING_FILTERS = {0: "linear", 1: "nearest", 2: "sharp", 3: "nis", 4: "pixel"}
SCALING_MODES = {0: "auto", 1: "integer", 2: "fit", 3: "fill", 4: "stretch"}
ATOMS = ["GAMESCOPE_FPS_LIMIT", "GAMESCOPE_NEW_SCALING_FILTER", "GAMESCOPE_NEW_SCALING_SCALER",
         "GAMESCOPE_FSR_SHARPNESS", "GAMESCOPE_ALLOW_TEARING"]


def _read_atoms() -> dict[str, int]:
    try:
        out = subprocess.run(
            ["xprop", "-root", *ATOMS], capture_output=True, text=True, timeout=5,
            env={**os.environ, "DISPLAY": GAMESCOPE_DISPLAY},
        ).stdout
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug(f"xprop failed: {e}")
        return {}
    return {m.group(1): int(m.group(2)) for m in re.finditer(r"^(\w+)\(CARDINAL\) = (\d+)", out, re.M)}


def _manual_gpu_clock() -> Optional[int]:
    try:
        if (DRM_DEVICE / "power_dpm_force_performance_level").read_text().strip() != "manual":
            return None
        sclk = re.findall(r"^\d:\s+(\d+)Mhz", (DRM_DEVICE / "pp_od_clk_voltage").read_text(), re.M)
    except OSError:
        return None
    # Manual GPU Clock pins min and max OD_SCLK to the same value
    return int(sclk[0]) if len(sclk) >= 2 and sclk[0] == sclk[1] else None


def _tdp_limit() -> Optional[float]:
    for hwmon in (DRM_DEVICE / "hwmon").glob("hwmon*"):
        try:
            return round(int((hwmon / "power1_cap").read_text()) / 1_000_000, 1)
        except (OSError, ValueError):
            continue
    return None


def read_live_settings() -> Optional[dict]:
    atoms = _read_atoms()
    if not atoms:
        return None
    settings = {
        "fps_limit": atoms.get("GAMESCOPE_FPS_LIMIT") or None,  # 0 = frame limit disabled
        "scaling_mode": SCALING_MODES.get(atoms.get("GAMESCOPE_NEW_SCALING_SCALER")),
        "scaling_filter": SCALING_FILTERS.get(atoms.get("GAMESCOPE_NEW_SCALING_FILTER")),
        "allow_tearing": bool(atoms.get("GAMESCOPE_ALLOW_TEARING")),
        "gpu_clock": _manual_gpu_clock(),
        "tdp": _tdp_limit(),
    }
    if settings["scaling_filter"] == "sharp" and "GAMESCOPE_FSR_SHARPNESS" in atoms:
        # gamescope counts down (0 = strongest); the menu's slider 5 = strongest
        settings["sharpness"] = max(0, 5 - atoms["GAMESCOPE_FSR_SHARPNESS"])
    return settings
