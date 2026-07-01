import logging
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Optional

from fps_monitor import GPUMonitor, SATURATED_THRESHOLD, HEADROOM_THRESHOLD

MIN_TDP = 3.0
MAX_TDP = 15.0

logger = logging.getLogger(__name__)

MIN_SAMPLES_TO_DECIDE = 18   # ~3 min at 10s effective sample rate
STEP_DOWN = 1.0              # watts to reduce when headroom detected
STEP_UP = 1.0                # watts to add when saturated
CONFIDENCE_PER_SESSION = 0.2 # reaches 1.0 after 5 sessions

THERMAL_PATHS = list(Path("/sys/class/thermal").glob("thermal_zone*/temp"))
THERMAL_LIMIT_C = 85.0       # cut TDP hard above this; deck hard-shuts around 93-95C
THERMAL_STEP_DOWN = 2.0      # watts to cut per hot tick — steeper than normal STEP_DOWN


def _read_temp_c() -> Optional[float]:
    best = None
    for p in THERMAL_PATHS:
        try:
            val = float(p.read_text().strip()) / 1000.0
        except (FileNotFoundError, ValueError, PermissionError):
            continue
        if best is None or val > best:
            best = val
    return best


class State(Enum):
    WARMING_UP = auto()   # not enough samples yet
    STABLE = auto()       # current TDP is good
    REDUCING = auto()     # trying lower TDP
    BOOSTING = auto()     # TDP was too low, recovering


@dataclass
class LearnerState:
    current_tdp: float
    state: State
    sessions_at_this_tdp: int = 0


def _snap(tdp: float) -> float:
    return float(max(MIN_TDP, min(MAX_TDP, round(tdp))))


class TDPLearner:
    def __init__(self, initial_tdp: Optional[float] = None):
        start = initial_tdp if initial_tdp is not None else MAX_TDP
        self.tdp = _snap(start)
        self.state = State.WARMING_UP
        self.monitor = GPUMonitor(window_seconds=180)

    def tick(self) -> None:
        """Call every SAMPLE_INTERVAL seconds while a game is running."""
        self.monitor.sample()

        temp = _read_temp_c()
        if temp is not None and temp >= THERMAL_LIMIT_C:
            self._thermal_cut(temp)
            return

        if self.monitor.sample_count() < MIN_SAMPLES_TO_DECIDE:
            return

        avg = self.monitor.avg()
        logger.debug(f"GPU avg={avg:.1f}% TDP={self.tdp}W state={self.state.name}")

        if self.state == State.WARMING_UP:
            self._evaluate_warmup()
        elif self.state == State.STABLE:
            self._check_stable()
        elif self.state == State.REDUCING:
            self._evaluate_reduction()
        elif self.state == State.BOOSTING:
            self._evaluate_boost()

    def get_learned_tdp(self) -> float:
        return self.tdp

    def session_ended(self) -> float:
        """Call on game exit. Returns the TDP learned this session."""
        logger.info(f"Session ended. Learned TDP={self.tdp}W state={self.state.name}")
        return self.tdp

    def _evaluate_warmup(self) -> None:
        if self.monitor.has_headroom():
            self.state = State.REDUCING
            self._reduce_tdp()
        elif self.monitor.is_saturated():
            self.state = State.STABLE
        else:
            self.state = State.STABLE

    def _check_stable(self) -> None:
        if self.monitor.has_headroom():
            self.state = State.REDUCING
            self._reduce_tdp()
        elif self.monitor.is_saturated() and self.tdp < MAX_TDP:
            self.state = State.BOOSTING
            self._boost_tdp()

    def _evaluate_reduction(self) -> None:
        if self.monitor.is_saturated():
            self._boost_tdp()
            self.state = State.STABLE
            logger.info(f"Found floor at {self.tdp}W")
        elif self.monitor.has_headroom():
            self._reduce_tdp()
        else:
            self.state = State.STABLE

    def _evaluate_boost(self) -> None:
        if not self.monitor.is_saturated():
            self.state = State.STABLE
        elif self.tdp < MAX_TDP:
            self._boost_tdp()

    def _reduce_tdp(self) -> None:
        new = _snap(self.tdp - STEP_DOWN)
        if new < self.tdp:
            self.tdp = new
            self.monitor.reset()
            logger.info(f"Trying lower TDP: {self.tdp}W")

    def _boost_tdp(self) -> None:
        new = _snap(self.tdp + STEP_UP)
        if new > self.tdp:
            self.tdp = new
            self.monitor.reset()
            logger.info(f"Boosting TDP: {self.tdp}W")

    def _thermal_cut(self, temp: float) -> None:
        new = _snap(self.tdp - THERMAL_STEP_DOWN)
        self.monitor.reset()
        self.state = State.STABLE
        if new < self.tdp:
            self.tdp = new
            logger.warning(f"Thermal guard: {temp:.1f}C >= {THERMAL_LIMIT_C}C, cutting TDP to {self.tdp}W")
        else:
            logger.warning(f"Thermal guard: {temp:.1f}C >= {THERMAL_LIMIT_C}C, already at floor {self.tdp}W")
