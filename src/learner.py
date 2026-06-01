import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from fps_monitor import GameMonitor, SATURATED_THRESHOLD, HEADROOM_THRESHOLD
from tdp_controller import MIN_TDP, MAX_TDP, MAX_GFXCLK, MIN_GFXCLK, CLOCK_STEP, set_tdp, set_gfxclk

logger = logging.getLogger(__name__)

MIN_SAMPLES_TO_DECIDE = 18   # ~3 min at 10s effective sample rate
STEP_DOWN = 1.0              # watts to reduce when headroom detected
STEP_UP = 1.0                # watts to add when saturated
CONFIDENCE_PER_SESSION = 0.2 # reaches 1.0 after 5 sessions
STABLE_TICKS_FOR_CLOCK = 6   # ticks in STABLE before starting clock tuning


class State(Enum):
    WARMING_UP = auto()
    STABLE = auto()
    REDUCING = auto()
    BOOSTING = auto()
    CLOCK_TUNING = auto()
    CLOCK_STABLE = auto()


@dataclass
class LearnerState:
    current_tdp: float
    state: State
    sessions_at_this_tdp: int = 0


class TDPLearner:
    def __init__(
        self,
        app_id: str,
        target_fps: int = 40,
        initial_tdp: Optional[float] = None,
        initial_gfxclk: Optional[int] = None,
    ):
        self.tdp = initial_tdp if initial_tdp is not None else MAX_TDP
        self.gfxclk = initial_gfxclk if initial_gfxclk is not None else MAX_GFXCLK
        self._prev_gfxclk = self.gfxclk
        self.state = State.WARMING_UP
        self.monitor = GameMonitor(app_id=app_id, target_fps=target_fps)
        self._stable_ticks = 0
        set_tdp(self.tdp)
        self._gfxclk_supported = set_gfxclk(self.gfxclk)
        if not self._gfxclk_supported:
            logger.warning("gfxclk control unavailable — clock tuning disabled")

    def tick(self) -> None:
        self.monitor.sample()

        if self.monitor.sample_count() < MIN_SAMPLES_TO_DECIDE:
            return

        gpu = self.monitor.avg_gpu()
        fps = self.monitor.avg_fps()
        fps_str = f" fps={fps:.1f}" if fps is not None else ""
        logger.debug(
            f"GPU={gpu:.1f}%{fps_str} TDP={self.tdp}W gfxclk={self.gfxclk}MHz state={self.state.name}"
        )

        if self.state == State.WARMING_UP:
            self._evaluate_warmup()
        elif self.state == State.STABLE:
            self._check_stable()
        elif self.state == State.REDUCING:
            self._evaluate_reduction()
        elif self.state == State.BOOSTING:
            self._evaluate_boost()
        elif self.state == State.CLOCK_TUNING:
            self._evaluate_clock_tuning()
        elif self.state == State.CLOCK_STABLE:
            self._check_clock_stable()

    def session_ended(self) -> tuple[float, int]:
        logger.info(
            f"Session ended. TDP={self.tdp}W gfxclk={self.gfxclk}MHz state={self.state.name}"
        )
        self.monitor.close()
        return self.tdp, self.gfxclk

    def _evaluate_warmup(self) -> None:
        if self.monitor.has_headroom():
            self.state = State.REDUCING
            self._reduce_tdp()
        else:
            self.state = State.STABLE
            self._stable_ticks = 0

    def _check_stable(self) -> None:
        if self.monitor.has_headroom():
            self.state = State.REDUCING
            self._stable_ticks = 0
            self._reduce_tdp()
        elif self.monitor.is_saturated() and self.tdp < MAX_TDP:
            self.state = State.BOOSTING
            self._stable_ticks = 0
            self._boost_tdp()
        else:
            self._stable_ticks += 1
            if self._stable_ticks >= STABLE_TICKS_FOR_CLOCK and self._gfxclk_supported:
                self.state = State.CLOCK_TUNING
                self._stable_ticks = 0
                logger.info(f"TDP stable at {self.tdp}W — starting clock tuning")

    def _evaluate_reduction(self) -> None:
        if self.monitor.is_saturated():
            self._boost_tdp()
            self.state = State.STABLE
            self._stable_ticks = 0
            logger.info(f"Found TDP floor at {self.tdp}W")
        elif self.monitor.has_headroom():
            self._reduce_tdp()
        else:
            self.state = State.STABLE
            self._stable_ticks = 0

    def _evaluate_boost(self) -> None:
        if not self.monitor.is_saturated():
            self.state = State.STABLE
            self._stable_ticks = 0
        elif self.tdp < MAX_TDP:
            self._boost_tdp()

    def _evaluate_clock_tuning(self) -> None:
        if self.monitor.is_saturated():
            self.gfxclk = self._prev_gfxclk
            set_gfxclk(self.gfxclk)
            self.state = State.CLOCK_STABLE
            logger.info(f"Found gfxclk floor at {self.gfxclk}MHz")
        elif self.monitor.has_headroom():
            self._reduce_gfxclk()
        else:
            self.state = State.CLOCK_STABLE
            logger.info(f"gfxclk stable at {self.gfxclk}MHz")

    def _check_clock_stable(self) -> None:
        if self.monitor.is_saturated():
            new = min(MAX_GFXCLK, self.gfxclk + CLOCK_STEP)
            if new > self.gfxclk:
                self.gfxclk = new
                set_gfxclk(self.gfxclk)
                self.monitor.reset()
                logger.info(f"Clock pressure — raised to {self.gfxclk}MHz")
        elif self.monitor.has_headroom():
            self.state = State.CLOCK_TUNING
            logger.info("Clock headroom detected — re-entering clock tuning")

    def _reduce_tdp(self) -> None:
        new = max(MIN_TDP, self.tdp - STEP_DOWN)
        if new < self.tdp:
            self.tdp = new
            set_tdp(self.tdp)
            self.monitor.reset()
            logger.info(f"Trying lower TDP: {self.tdp}W")

    def _boost_tdp(self) -> None:
        new = min(MAX_TDP, self.tdp + STEP_UP)
        if new > self.tdp:
            self.tdp = new
            set_tdp(self.tdp)
            self.monitor.reset()
            logger.info(f"Boosting TDP: {self.tdp}W")

    def _reduce_gfxclk(self) -> None:
        new = max(MIN_GFXCLK, self.gfxclk - CLOCK_STEP)
        if new < self.gfxclk:
            self._prev_gfxclk = self.gfxclk
            self.gfxclk = new
            set_gfxclk(self.gfxclk)
            self.monitor.reset()
            logger.info(f"Trying lower gfxclk: {self.gfxclk}MHz")
