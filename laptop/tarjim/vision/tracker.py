"""Read a line once, when it is stable; then track it cheaply until it leaves.

Feed every frame's detection to `SubtitleTracker.update`. It returns one event:
  NONE     nothing to do
  NEW      a block became stable: OCR, translate, render and show it
  REFRESH  the shown block is still there: refresh the fill from this frame
  GONE     the shown block left or changed: clear the overlay
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .detect import Block, mask_iou


class Event(Enum):
    NONE = "none"
    NEW = "new"
    REFRESH = "refresh"
    GONE = "gone"


@dataclass(frozen=True)
class TrackParams:
    settle_ms: float = 150.0
    stable_iou: float = 0.90
    keep_iou: float = 0.60
    gone_iou: float = 0.30
    gone_frames: int = 2
    grow_ratio: float = 1.03  # mask area growth that still counts as "typing"


class SubtitleTracker:
    def __init__(self, params: TrackParams | None = None) -> None:
        self.p = params or TrackParams()
        self.shown: Block | None = None  # reference mask of the block on screen
        self._cand: Block | None = None
        self._cand_since = 0.0
        self._misses = 0
        self._rejected: Block | None = None

    @staticmethod
    def _area(block: Block) -> int:
        return int((block.mask > 0).sum())

    def reject(self) -> None:
        """The consumer decided the last NEW block is not a subtitle (bad OCR)."""
        self._rejected = self.shown
        self.shown = None

    def reset(self) -> None:
        self.shown = None
        self._cand = None
        self._misses = 0
        self._rejected = None

    def update(self, block: Block | None, t_ms: float) -> Event:
        p = self.p
        if self.shown is not None:
            iou = mask_iou(self.shown, block)
            if iou >= p.keep_iou:
                self._misses = 0
                return Event.REFRESH
            if iou < p.gone_iou or block is None:
                self._misses += 1
                if self._misses >= p.gone_frames:
                    self.shown = None
                    self._misses = 0
                    self._cand = block
                    self._cand_since = t_ms
                    return Event.GONE
                return Event.NONE
            # In between: text in the same place that no longer matches. Treat as different text.
            self.shown = None
            self._misses = 0
            self._cand = block
            self._cand_since = t_ms
            return Event.GONE

        if block is None:
            self._cand = None
            self._rejected = None
            return Event.NONE
        if self._rejected is not None:
            if mask_iou(self._rejected, block) >= p.keep_iou:
                return Event.NONE  # the same non-subtitle is still there
            self._rejected = None
        if self._cand is None:
            self._cand, self._cand_since = block, t_ms
            return Event.NONE
        iou = mask_iou(self._cand, block)
        growing = self._area(block) > self._area(self._cand) * p.grow_ratio
        if iou < p.stable_iou or growing:
            self._cand, self._cand_since = block, t_ms  # still changing (typewriter text)
            return Event.NONE
        if t_ms - self._cand_since >= p.settle_ms:
            self.shown = block
            self._cand = None
            self._misses = 0
            return Event.NEW
        return Event.NONE
