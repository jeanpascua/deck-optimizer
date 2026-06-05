import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MIN_TDP = 3.0   # watts
MAX_TDP = 15.0  # watts

STATE_FILE = Path.home() / ".local" / "share" / "deck-auto-tdp" / "active-tdp"


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
