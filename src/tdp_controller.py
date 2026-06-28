import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MIN_TDP = 3.0   # watts
MAX_TDP = 15.0  # watts
MIN_GPU_CLOCK = 200   # MHz
MAX_GPU_CLOCK = 1600  # MHz

STATE_DIR = Path.home() / ".local" / "share" / "deck-optimizer"
STATE_FILE = STATE_DIR / "active-tdp"
GPU_CLOCK_PATH = Path("/sys/class/drm/card0/device/pp_od_clk_voltage")
FPS_LIMIT_PATH = Path.home() / ".local" / "share" / "deck-optimizer" / "active-fps"


def set_tdp(watts: float) -> bool:
    watts = max(MIN_TDP, min(MAX_TDP, round(watts, 1)))
    mw = int(watts * 1000)
    try:
        subprocess.run(
            [
                "ryzenadj",
                f"--stapm-limit={mw}",
                f"--fast-limit={mw}",
                f"--slow-limit={mw}",
            ],
            check=True,
            capture_output=True,
            timeout=5,
        )
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(str(watts))
        logger.info(f"TDP → {watts}W")
        return True
    except FileNotFoundError:
        logger.error("ryzenadj not found — install it first")
        return False
    except subprocess.CalledProcessError as e:
        logger.error(f"ryzenadj failed: {e.stderr.decode()}")
        return False
    except subprocess.TimeoutExpired:
        logger.error("ryzenadj timed out")
        return False


def set_gpu_clock(mhz: int) -> bool:
    mhz = round(mhz / 100) * 100
    mhz = max(MIN_GPU_CLOCK, min(MAX_GPU_CLOCK, mhz))
    try:
        subprocess.run(
            ["ryzenadj", f"--gfx-clk={mhz}"],
            check=True, capture_output=True, timeout=5,
        )
        logger.info(f"GPU clock → {mhz}MHz")
        return True
    except FileNotFoundError:
        logger.error("ryzenadj not found")
        return False
    except subprocess.CalledProcessError as e:
        logger.error(f"GPU clock set failed: {e.stderr.decode()}")
        return False
    except subprocess.TimeoutExpired:
        logger.error("ryzenadj timed out")
        return False


def clear_gpu_clock() -> bool:
    try:
        subprocess.run(
            ["ryzenadj", f"--gfx-clk={MAX_GPU_CLOCK}"],
            check=True, capture_output=True, timeout=5,
        )
        logger.info(f"GPU clock reset to {MAX_GPU_CLOCK}MHz")
        return True
    except Exception:
        return False


def set_fps_limit(fps: int) -> bool:
    allowed = [0, 15, 30, 40, 60]
    if fps not in allowed:
        fps = min(allowed, key=lambda x: abs(x - fps))
    try:
        env_file = Path.home() / ".local" / "share" / "deck-optimizer" / "gamescope-fps"
        env_file.parent.mkdir(parents=True, exist_ok=True)
        env_file.write_text(str(fps))
        subprocess.run(
            ["mangohud-control", "set", f"fps_limit={fps}"],
            capture_output=True, timeout=5,
        )
        logger.info(f"FPS limit → {fps}")
        return True
    except FileNotFoundError:
        logger.debug("mangohud-control not found, FPS limit saved for manual apply")
        return False
    except Exception as e:
        logger.warning(f"FPS limit failed: {e}")
        return False


def clear_fps_limit() -> bool:
    try:
        subprocess.run(
            ["mangohud-control", "set", "fps_limit=0"],
            capture_output=True, timeout=5,
        )
        logger.info("FPS limit cleared")
        return True
    except Exception:
        return False


def clear_active_tdp() -> None:
    if STATE_FILE.exists():
        STATE_FILE.unlink()


def get_current_tdp() -> Optional[float]:
    try:
        result = subprocess.run(
            ["ryzenadj", "--info"], capture_output=True, text=True, check=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if "STAPM LIMIT" in line and "|" in line:
                value = line.split("|")[1].strip()
                return float(value) / 1000
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError, subprocess.TimeoutExpired):
        pass
    return None
