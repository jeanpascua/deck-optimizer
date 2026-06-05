#!/usr/bin/env python3
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tdp_controller import STATE_FILE, set_tdp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    if not STATE_FILE.exists():
        logger.info("No active TDP state — nothing to restore after resume")
        return
    try:
        tdp = float(STATE_FILE.read_text().strip())
        if set_tdp(tdp):
            logger.info(f"Restored TDP to {tdp}W after resume")
        else:
            logger.error("Failed to restore TDP after resume")
            sys.exit(1)
    except (ValueError, OSError) as e:
        logger.error(f"Bad state file: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
