import logging
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

MIN_TDP = 3.0   # watts
MAX_TDP = 15.0  # watts
RYZENADJ = "/home/deck/.local/bin/ryzenadj"

MAX_GFXCLK = 1600  # MHz, Steam Deck hardware max
MIN_GFXCLK = 400
CLOCK_STEP = 100


def set_tdp(watts: float) -> bool:
    watts = max(MIN_TDP, min(MAX_TDP, round(watts, 1)))
    mw = int(watts * 1000)
    try:
        subprocess.run(
            [
                RYZENADJ,
                f"--stapm-limit={mw}",
                f"--fast-limit={mw}",
                f"--slow-limit={mw}",
            ],
            check=True,
            capture_output=True,
            timeout=5,
        )
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


def set_gfxclk(mhz: int) -> bool:
    mhz = max(MIN_GFXCLK, min(MAX_GFXCLK, mhz))
    try:
        subprocess.run(
            [RYZENADJ, f"--max-gfxclk={mhz}"],
            check=True,
            capture_output=True,
            timeout=5,
        )
        logger.info(f"GFX clock → {mhz}MHz")
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


def get_current_tdp() -> Optional[float]:
    try:
        result = subprocess.run(
            [RYZENADJ, "--info"], capture_output=True, text=True, check=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if "STAPM LIMIT" in line and "|" in line:
                value = line.split("|")[1].strip()
                return float(value) / 1000
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError, subprocess.TimeoutExpired):
        pass
    return None
