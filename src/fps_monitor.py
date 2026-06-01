import logging
import os
import time
from collections import deque
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

GPU_BUSY_PATH = Path("/sys/class/drm/card0/device/gpu_busy_percent")
STATS_PIPE = Path("/run/user/1000/gamescope-stats/stats.pipe")

SATURATED_THRESHOLD = 88.0
HEADROOM_THRESHOLD = 62.0
SAMPLE_INTERVAL = 5
FPS_MARGIN = 3.0  # fps tolerance around target before acting


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


class FPSMonitor:
    def __init__(self, app_id: str, window_seconds: int = 60):
        self.app_id = app_id
        self.window_seconds = window_seconds
        self._samples: deque[tuple[float, float]] = deque()
        self._fd: Optional[int] = None
        self._buf = ""
        self._focus: Optional[str] = None
        self._open_pipe()

    def _open_pipe(self) -> None:
        try:
            fd = os.open(str(STATS_PIPE), os.O_RDONLY | os.O_NONBLOCK)
            self._fd = fd
            logger.info(f"Opened gamescope stats pipe (app_id={self.app_id})")
        except OSError as e:
            logger.warning(f"Cannot open gamescope stats pipe: {e}")

    def sample(self) -> None:
        if self._fd is None:
            self._open_pipe()
            return
        try:
            chunk = os.read(self._fd, 8192).decode("utf-8", errors="ignore")
            self._buf += chunk
        except BlockingIOError:
            return
        except OSError:
            self.close()
            return

        lines = self._buf.split("\n")
        self._buf = lines[-1]
        now = time.monotonic()

        for line in lines[:-1]:
            line = line.strip()
            if line.startswith("focus="):
                self._focus = line[6:]
            elif line.startswith("fps=") and self._focus == self.app_id:
                try:
                    fps = float(line[4:])
                    if fps > 0:
                        self._samples.append((now, fps))
                except ValueError:
                    pass

        self._trim(now)

    def avg(self) -> Optional[float]:
        if not self._samples:
            return None
        return sum(s[1] for s in self._samples) / len(self._samples)

    def has_data(self) -> bool:
        return bool(self._samples)

    def is_below_target(self, target: float) -> bool:
        a = self.avg()
        return a is not None and a < target - FPS_MARGIN

    def is_above_target(self, target: float) -> bool:
        a = self.avg()
        return a is not None and a > target + FPS_MARGIN

    def reset(self) -> None:
        self._samples.clear()

    def close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def _trim(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()


class GameMonitor:
    """Composite monitor: GPU util + FPS from gamescope stats pipe."""

    def __init__(self, app_id: str, target_fps: int = 40, window_seconds: int = 180):
        self.target_fps = target_fps
        self._gpu = GPUMonitor(window_seconds)
        self._fps = FPSMonitor(app_id)

    def sample(self) -> None:
        self._gpu.sample()
        self._fps.sample()

    def sample_count(self) -> int:
        return self._gpu.sample_count()

    def avg_gpu(self) -> Optional[float]:
        return self._gpu.avg()

    def avg_fps(self) -> Optional[float]:
        return self._fps.avg()

    def is_saturated(self) -> bool:
        if self._fps.has_data():
            return self._fps.is_below_target(self.target_fps)
        return self._gpu.is_saturated()

    def has_headroom(self) -> bool:
        gpu_ok = self._gpu.has_headroom()
        if self._fps.has_data():
            return gpu_ok and self._fps.is_above_target(self.target_fps)
        return gpu_ok

    def reset(self) -> None:
        self._gpu.reset()
        self._fps.reset()

    def close(self) -> None:
        self._fps.close()
