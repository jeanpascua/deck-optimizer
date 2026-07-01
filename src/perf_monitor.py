#!/usr/bin/env python3
"""Performance monitoring during gameplay — GPU, power, temp, battery, FPS."""

import logging
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

GPU_BUSY_PATH = Path("/sys/class/drm/card0/device/gpu_busy_percent")
BATTERY_CAPACITY_PATH = Path("/sys/class/power_supply/BAT1/capacity")
BATTERY_VOLTAGE_PATH = Path("/sys/class/power_supply/BAT1/voltage_now")
BATTERY_CURRENT_PATH = Path("/sys/class/power_supply/BAT1/current_now")
THERMAL_PATHS = list(Path("/sys/class/thermal").glob("thermal_zone*/temp"))


@dataclass
class PerfSample:
    timestamp: float
    gpu_busy_pct: Optional[float]
    battery_pct: Optional[int]
    power_watts: Optional[float]
    temp_c: Optional[float]
    fps: Optional[float]


@dataclass
class SessionStats:
    session_start: str
    session_duration_min: float
    sample_count: int
    gpu_busy_avg: Optional[float]
    gpu_busy_max: Optional[float]
    gpu_busy_min: Optional[float]
    power_watts_avg: Optional[float]
    power_watts_max: Optional[float]
    temp_c_avg: Optional[float]
    temp_c_max: Optional[float]
    battery_start_pct: Optional[int]
    battery_end_pct: Optional[int]
    battery_drain_pct: Optional[int]
    fps_avg: Optional[float]
    fps_min: Optional[float]


def _read_sysfs_float(path: Path) -> Optional[float]:
    try:
        return float(path.read_text().strip())
    except (FileNotFoundError, ValueError, PermissionError):
        return None


def _read_sysfs_int(path: Path) -> Optional[int]:
    try:
        return int(path.read_text().strip())
    except (FileNotFoundError, ValueError, PermissionError):
        return None


def _read_temp() -> Optional[float]:
    best = None
    for p in THERMAL_PATHS:
        val = _read_sysfs_float(p)
        if val is not None:
            temp_c = val / 1000.0
            if best is None or temp_c > best:
                best = temp_c
    return best


def _read_power() -> Optional[float]:
    v = _read_sysfs_float(BATTERY_VOLTAGE_PATH)
    i = _read_sysfs_float(BATTERY_CURRENT_PATH)
    if v is not None and i is not None:
        return round((v * i) / 1e12, 2)
    return None


def _read_fps() -> Optional[float]:
    try:
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                environ = (proc / "environ").read_bytes().decode("utf-8", errors="ignore")
                env = dict(v.split("=", 1) for v in environ.split("\x00") if "=" in v)
                stats_path = env.get("GAMESCOPE_STATS")
                if not stats_path:
                    continue
                fd = os.open(stats_path, os.O_RDONLY | os.O_NONBLOCK)
                try:
                    data = os.read(fd, 4096).decode("utf-8", errors="ignore")
                    for line in data.splitlines():
                        if line.startswith("fps="):
                            return float(line.split("=", 1)[1])
                finally:
                    os.close(fd)
            except (PermissionError, ValueError, OSError):
                continue
    except Exception:
        pass
    return None


class SessionMonitor:
    def __init__(self):
        self._start_time = time.monotonic()
        self._start_iso = datetime.now(timezone.utc).isoformat()
        self._samples: list[PerfSample] = []
        self._battery_start = _read_sysfs_int(BATTERY_CAPACITY_PATH)

    def sample(self) -> None:
        s = PerfSample(
            timestamp=time.monotonic(),
            gpu_busy_pct=_read_sysfs_float(GPU_BUSY_PATH),
            battery_pct=_read_sysfs_int(BATTERY_CAPACITY_PATH),
            power_watts=_read_power(),
            temp_c=_read_temp(),
            fps=_read_fps(),
        )
        self._samples.append(s)

    def summarize(self) -> SessionStats:
        duration = (time.monotonic() - self._start_time) / 60.0
        count = len(self._samples)

        gpu_vals = [s.gpu_busy_pct for s in self._samples if s.gpu_busy_pct is not None]
        power_vals = [s.power_watts for s in self._samples if s.power_watts is not None]
        temp_vals = [s.temp_c for s in self._samples if s.temp_c is not None]
        fps_vals = [s.fps for s in self._samples if s.fps is not None]

        battery_end = _read_sysfs_int(BATTERY_CAPACITY_PATH)
        battery_drain = None
        if self._battery_start is not None and battery_end is not None:
            battery_drain = self._battery_start - battery_end

        return SessionStats(
            session_start=self._start_iso,
            session_duration_min=round(duration, 1),
            sample_count=count,
            gpu_busy_avg=round(sum(gpu_vals) / len(gpu_vals), 1) if gpu_vals else None,
            gpu_busy_max=round(max(gpu_vals), 1) if gpu_vals else None,
            gpu_busy_min=round(min(gpu_vals), 1) if gpu_vals else None,
            power_watts_avg=round(sum(power_vals) / len(power_vals), 1) if power_vals else None,
            power_watts_max=round(max(power_vals), 1) if power_vals else None,
            temp_c_avg=round(sum(temp_vals) / len(temp_vals), 1) if temp_vals else None,
            temp_c_max=round(max(temp_vals), 1) if temp_vals else None,
            battery_start_pct=self._battery_start,
            battery_end_pct=battery_end,
            battery_drain_pct=battery_drain,
            fps_avg=round(sum(fps_vals) / len(fps_vals), 1) if fps_vals else None,
            fps_min=round(min(fps_vals), 1) if fps_vals else None,
        )
