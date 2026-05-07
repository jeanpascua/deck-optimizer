import logging
import time
from collections import deque
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

GPU_BUSY_PATH = Path("/sys/class/drm/card0/device/gpu_busy_percent")

# GPU busy % thresholds for learning decisions
SATURATED_THRESHOLD = 88.0   # game is GPU-bound; TDP may be limiting
HEADROOM_THRESHOLD = 62.0    # clear headroom; TDP can be reduced
SAMPLE_INTERVAL = 5          # seconds between samples


class GPUMonitor:
    def __init__(self, window_seconds: int = 180):
        self.window_seconds = window_seconds
        self._samples: deque[tuple[float, float]] = deque()

    def sample(self) -> Optional[float]:
        try:
            pct = float(GPU_BUSY_PATH.read_text().strip())
            now = time.monotonic()
            self._samples.append((now, pct))
            self._trim(now)
            return pct
        except (FileNotFoundError, ValueError) as e:
            logger.warning(f"GPU busy read failed: {e}")
            return None

    def avg(self) -> Optional[float]:
        if not self._samples:
            return None
        return sum(s[1] for s in self._samples) / len(self._samples)

    def sample_count(self) -> int:
        return len(self._samples)

    def is_saturated(self) -> bool:
        a = self.avg()
        return a is not None and a >= SATURATED_THRESHOLD

    def has_headroom(self) -> bool:
        a = self.avg()
        return a is not None and a <= HEADROOM_THRESHOLD

    def reset(self) -> None:
        self._samples.clear()

    def _trim(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()
