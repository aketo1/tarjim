"""The live loop: frame -> detect -> stable? -> OCR -> translate -> render -> TV."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import paths
from . import protocol as P
from .translate import CachedTranslator, TranslateError
from .tvlink import TvLink, TvLinkError, now_ms
from .vision import render
from .vision.detect import Block, DetectParams, detect
from .vision.ocr import OcrEngine
from .vision.tracker import Event, SubtitleTracker, TrackParams

LAYER_TTL_MS = 700
FILL_REFRESH_MS = 85  # about 12 fill refreshes per second
HOLD_KEEP_MS = 200


def reading_time_ms(arabic: str) -> float:
    """How long a line must stay up to be read: about 15 characters per second, 1.6 to 6 s."""
    return float(min(6000.0, max(1600.0, 900.0 + 65.0 * len(arabic))))


@dataclass
class StageTimes:
    detect: list[float] = field(default_factory=list)
    ocr: list[float] = field(default_factory=list)
    mt: list[float] = field(default_factory=list)
    mt_cached: list[float] = field(default_factory=list)
    render: list[float] = field(default_factory=list)
    tv: list[float] = field(default_factory=list)  # send -> drawn, from the TV's ack
    total: list[float] = field(default_factory=list)  # stable -> drawn on the TV
    refresh: list[float] = field(default_factory=list)

    def summary(self) -> dict[str, dict[str, float]]:
        out = {}
        for name, values in self.__dict__.items():
            if values:
                a = np.array(values)
                out[name] = {"n": len(values), "p50": float(np.percentile(a, 50)), "p90": float(np.percentile(a, 90))}
        return out


class Pipeline:
    def __init__(
        self,
        link: TvLink,
        translator: CachedTranslator,
        ocr: OcrEngine | None = None,
        *,
        window: str = "A",
        style: render.Style | None = None,
        detect_params: DetectParams | None = None,
        track_params: TrackParams | None = None,
        log_path: Path | None = None,
        show_fill: bool = True,
    ) -> None:
        self.link = link
        self.translator = translator
        self.ocr = ocr or OcrEngine()
        self.window = window
        self.style = style or render.Style()
        self.detect_params = detect_params or DetectParams()
        self.tracker = SubtitleTracker(track_params)
        self.times = StageTimes()
        self.show_fill = show_fill
        self.enabled = True
        self.lines_shown = 0
        self.rejected = 0
        self._text_up = False
        self._last_fill = 0.0
        self._shown_at = 0.0  # when the current Arabic line went up (laptop ms)
        self._read_ms = 0.0
        self._holding = False  # English gone, Arabic kept up so it can be read
        self._text_layer: render.RgbaLayer | None = None
        self._frame_shape = (1080, 1920)
        self._last_keep = 0.0
        self.held = 0
        self._log = log_path.open("a", encoding="utf-8") if log_path else None
        self._pending: dict[int, dict] = {}

    # -- geometry -----------------------------------------------------------

    def _to_overlay(self, layer: render.RgbaLayer, frame_shape) -> P.Layer:
        ow, oh = self.link.caps.get("w", 1920), self.link.caps.get("h", 1080)
        fh, fw = frame_shape[:2]
        bgra = layer.bgra
        x, y = layer.x, layer.y
        if (fw, fh) != (ow, oh):  # render size differs from the overlay plane: scale once, here
            sx, sy = ow / fw, oh / fh
            x0, y0 = int(round(x * sx)), int(round(y * sy))
            x1, y1 = int(round((x + layer.w) * sx)), int(round((y + layer.h) * sy))
            bgra = cv2.resize(bgra, (max(1, x1 - x0), max(1, y1 - y0)), interpolation=cv2.INTER_AREA)
            x, y = x0, y0
        h = min(bgra.shape[0], P.MAX_LAYER_H)
        w = min(bgra.shape[1], P.MAX_LAYER_W)
        bgra = np.ascontiguousarray(bgra[:h, :w])
        ok, buf = cv2.imencode(".png", bgra, [cv2.IMWRITE_PNG_COMPRESSION, 1])
        if not ok:
            raise RuntimeError("PNG encoding failed")
        return P.Layer(id=layer.id, png=buf.tobytes(), x=int(x), y=int(y), w=w, h=h, z=layer.z, ttl_ms=LAYER_TTL_MS)

    # -- per frame ------------------------------------------------------------

    def process(self, frame: np.ndarray, t_capture: float) -> Event:
        """Handle one frame. `t_capture` is time.monotonic() seconds."""
        t0 = time.perf_counter()
        block = detect(frame, self.detect_params)
        self.times.detect.append((time.perf_counter() - t0) * 1000.0)
        event = self.tracker.update(block, t_capture * 1000.0)
        try:
            if event is Event.NEW:
                self._on_new(frame, self.tracker.shown, t_capture)
            elif event is Event.REFRESH:
                self._on_refresh(frame)
            elif event is Event.GONE:
                self._on_gone()
            if self._holding:
                self._hold_tick()
        except TvLinkError:
            self._text_up = False  # the TV clears by itself when the link drops
            self._holding = False
        self._collect_acks()
        return event

    def _on_new(self, frame: np.ndarray, block: Block, t_capture: float) -> None:
        t_stable = now_ms()
        t = time.perf_counter()
        read = self.ocr.read(frame, block)
        ocr_ms = (time.perf_counter() - t) * 1000.0
        self.times.ocr.append(ocr_ms)
        if not read.ok:
            self.rejected += 1
            self.tracker.reject()
            return
        try:
            arabic, hit, mt_ms = self.translator.translate(read.text)
        except TranslateError:
            self.rejected += 1
            self.tracker.reject()
            return
        (self.times.mt_cached if hit else self.times.mt).append(mt_ms)
        if not self.enabled:
            return
        t = time.perf_counter()
        layers = []
        if self.show_fill:
            layers.append(self._to_overlay(render.make_fill(frame, block), frame.shape))
        text_layer = render.make_text(frame, block, arabic, self.style)
        layers.append(self._to_overlay(text_layer, frame.shape))
        render_ms = (time.perf_counter() - t) * 1000.0
        self.times.render.append(render_ms)
        t_sent = now_ms()
        if self._holding:  # a new line replaces the one being held: drop its plate first
            self.link.clear(["plate"])
            self._holding = False
        seq = self.link.show(self.window, layers)
        self._text_up = True
        self._last_fill = t_sent
        self._shown_at = t_sent
        self._read_ms = reading_time_ms(arabic)
        self._text_layer = text_layer
        self._frame_shape = frame.shape
        self.lines_shown += 1
        self._pending[seq] = {
            "t_frame": t_capture * 1000.0, "t_stable": t_stable, "t_sent": t_sent,
            "ocr_ms": round(ocr_ms, 1), "mt_ms": round(mt_ms, 1), "render_ms": round(render_ms, 1),
            "en": read.text, "ar": arabic, "speaker": read.speaker, "ocr_score": round(read.score, 3),
            "engine": self.translator.engine.name, "cache_hit": hit, "mode": "replace",
        }

    def _on_refresh(self, frame: np.ndarray) -> None:
        if not self._text_up or not self.enabled or self._holding:
            return
        now = now_ms()
        if now - self._last_fill < FILL_REFRESH_MS:
            return
        t = time.perf_counter()
        if self.show_fill:
            fill = self._to_overlay(render.make_fill(frame, self.tracker.shown), frame.shape)
            self.link.show(self.window, [fill])
        self.link.keep(["text"] if self.show_fill else ["text"])
        self._last_fill = now
        self.times.refresh.append((time.perf_counter() - t) * 1000.0)

    def _on_gone(self) -> None:
        """The English left. Keep the Arabic until it has had its reading time."""
        if not self._text_up or self._holding:
            return
        remaining = self._shown_at + self._read_ms - now_ms()
        if remaining <= 150 or self._text_layer is None or not self.enabled:
            self._clear()
            return
        # No English underneath any more: swap the stroke fill for a dark plate,
        # which also hides the next English line until its own Arabic is ready.
        plate = self._to_overlay(render.make_plate(self._text_layer, self._frame_shape), self._frame_shape)
        self.link.show(self.window, [plate])
        self.link.clear(["fill"])
        self.link.keep(["text"])
        self._holding = True
        self._last_keep = now_ms()
        self.held += 1

    def _hold_tick(self) -> None:
        now = now_ms()
        if now >= self._shown_at + self._read_ms:
            self._clear()
        elif now - self._last_keep >= HOLD_KEEP_MS:
            self.link.keep(["text", "plate"])
            self._last_keep = now

    def _clear(self) -> None:
        if self._text_up:
            self.link.clear(None)
        self._text_up = False
        self._holding = False

    def set_enabled(self, on: bool) -> None:
        self.enabled = on
        if not on:
            try:
                self._clear()
            except TvLinkError:
                pass
            self.tracker.reset()

    def _collect_acks(self) -> None:
        for seq in list(self._pending):
            ack = self.link.wait_ack(seq, timeout=0.0)
            if ack is None:
                if now_ms() - self._pending[seq]["t_sent"] > 3000:
                    self._write_log(self._pending.pop(seq))
                continue
            rec = self._pending.pop(seq)
            if ack.get("t_drawn") is not None:
                drawn = self.link.tv_time_to_laptop(float(ack["t_drawn"]))
                if drawn is not None:
                    rec["t_tv_drawn"] = drawn
                    rec["tv_ms"] = round(drawn - rec["t_sent"], 1)
                    rec["total_ms"] = round(drawn - rec["t_stable"], 1)
                    self.times.tv.append(rec["tv_ms"])
                    self.times.total.append(rec["total_ms"])
            self._write_log(rec)

    def _write_log(self, rec: dict) -> None:
        if self._log:
            self._log.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self._log.flush()

    def close(self) -> None:
        try:
            self._clear()
        except TvLinkError:
            pass
        deadline = time.monotonic() + 0.5
        while self._pending and time.monotonic() < deadline:
            self._collect_acks()
            time.sleep(0.02)
        for rec in self._pending.values():
            self._write_log(rec)
        self._pending.clear()
        if self._log:
            self._log.close()


def new_log_path() -> Path:
    d = paths.REPO / "out" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"session-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
