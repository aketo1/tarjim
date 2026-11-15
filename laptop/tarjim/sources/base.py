"""The FrameSource interface and the hand-off box backends share."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Iterator, Protocol

import numpy as np


class SourceError(Exception):
    pass


@dataclass(frozen=True)
class SourceInfo:
    backend: str
    width: int
    height: int
    fps: float  # measured over the last 2 seconds
    delay_ms: float | None  # estimated delay behind HDMI; None when unknown
    reconnects: int = 0
    dropped: int = 0  # frames the consumer never saw because it was slower than the source


class FrameSource(Protocol):
    def frames(self) -> Iterator[tuple[np.ndarray, float, int]]:
        """Yield (frame_bgr, t_capture, seq). t_capture is time.monotonic() seconds."""
        ...

    def info(self) -> SourceInfo: ...

    def close(self) -> None: ...


class FrameBox:
    """Holds only the newest frame. A producer thread puts, one consumer waits.

    The consumer always gets the latest picture; anything it was too slow for
    is counted as dropped instead of queued, so the pipeline never falls behind.
    """

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._item: tuple[object, float, int] | None = None
        self._seq = 0
        self._taken = 0
        self._arrivals: deque[float] = deque(maxlen=240)
        self.dropped = 0
        self.closed = False

    def put(self, frame: object, t_capture: float | None = None) -> int:
        now = time.monotonic() if t_capture is None else t_capture
        with self._cond:
            self._seq += 1
            self._item = (frame, now, self._seq)
            self._arrivals.append(now)
            self._cond.notify_all()
            return self._seq

    def get(self, timeout: float | None = None) -> tuple[object, float, int] | None:
        """Wait for a frame newer than the last one returned. None on timeout or close."""
        with self._cond:
            if not self._cond.wait_for(lambda: self.closed or self._seq > self._taken, timeout):
                return None
            if self._seq <= self._taken:
                return None  # closed with nothing new
            frame, t, seq = self._item
            self.dropped += seq - self._taken - 1
            self._taken = seq
            return frame, t, seq

    def close(self) -> None:
        with self._cond:
            self.closed = True
            self._cond.notify_all()

    @property
    def seq(self) -> int:
        return self._seq

    @property
    def last_arrival(self) -> float | None:
        with self._cond:
            return self._arrivals[-1] if self._arrivals else None

    def fps(self, window: float = 2.0) -> float:
        cutoff = time.monotonic() - window
        with self._cond:
            return sum(1 for t in self._arrivals if t > cutoff) / window
