"""`file` backend: replay an image, an image folder or a video. No console needed."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Iterator

import numpy as np
from PIL import Image

from .base import SourceError, SourceInfo

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
VIDEO_EXT = {".mp4", ".mkv", ".mov", ".ts", ".webm", ".avi"}


class FileSource:
    """Plays frames at `fps` in real time (fps=0: as fast as the consumer reads)."""

    def __init__(self, path: str | Path, fps: float = 30.0, loop: bool = False) -> None:
        self.path = Path(path)
        self.fps = float(fps)
        self.loop = loop
        self._size = (0, 0)
        self._closed = False
        if self.path.is_dir():
            self._images = sorted(p for p in self.path.iterdir() if p.suffix.lower() in IMAGE_EXT)
            if not self._images:
                raise SourceError(f"no images in {self.path}")
            self._video = None
        elif self.path.suffix.lower() in IMAGE_EXT and self.path.exists():
            self._images, self._video = [self.path], None
        elif self.path.suffix.lower() in VIDEO_EXT and self.path.exists():
            self._images, self._video = [], self.path
        else:
            raise SourceError(f"not an image, image folder or video: {self.path}")

    def _raw_frames(self) -> Iterator[np.ndarray]:
        if self._video is None:
            for p in self._images:
                with Image.open(p) as img:
                    rgb = np.asarray(img.convert("RGB"))
                yield np.ascontiguousarray(rgb[:, :, ::-1])
            return
        import av

        with av.open(str(self._video)) as container:
            for frame in container.decode(video=0):
                yield frame.to_ndarray(format="bgr24")

    def frames(self) -> Iterator[tuple[np.ndarray, float, int]]:
        seq = 0
        start = time.monotonic()
        while not self._closed:
            for frame in self._raw_frames():
                if self._closed:
                    return
                seq += 1
                if self.fps > 0:
                    due = start + (seq - 1) / self.fps
                    delay = due - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                self._size = (frame.shape[1], frame.shape[0])
                yield frame, time.monotonic(), seq
            if not self.loop:
                return

    def info(self) -> SourceInfo:
        return SourceInfo("file", self._size[0], self._size[1], self.fps, delay_ms=0.0)

    def close(self) -> None:
        self._closed = True
