"""Erase and replace: cover the English strokes, draw Arabic in the same place and style.

Produces RGBA layers in overlay pixels (see section 7 of the brief):
`fill` (estimated background on the grown stroke mask), `text` (Arabic glyphs
plus shadow) and, for the frost and dim modes, `plate`.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from . import arabic
from .detect import Block


@dataclass(frozen=True)
class Style:
    font: str = "harmattan"
    size_factor: float = 1.0
    shadow_offset: tuple[int, int] = (2, 2)
    shadow_sigma: float = 2.2
    shadow_opacity: float = 0.9
    color: tuple[int, int, int] | None = None  # BGR; None = sample from the English strokes
    max_shrink: float = 0.88
    # One size for the whole session: when set, the size is never measured or
    # shrunk per line; a line that does not fit wraps onto another line instead.
    fixed_size: int | None = None
    min_wrap_width: int = 1000  # px at 1080p: Arabic may run wider than a short English line
    effect: str = "shadow"  # "shadow" (soft drop shadow), "outline" (dark edge all round) or "none"
    outline_px: int = 3
    y_offset: int = 0  # move the Arabic up (negative) or down (positive), in pixels at 1080p


@dataclass
class RgbaLayer:
    """An RGBA image (BGRA channel order in memory) placed at integer overlay pixels."""

    id: str
    x: int
    y: int
    bgra: np.ndarray
    z: int = 0

    @property
    def w(self) -> int:
        return self.bgra.shape[1]

    @property
    def h(self) -> int:
        return self.bgra.shape[0]

    def png(self) -> bytes:
        ok, buf = cv2.imencode(".png", self.bgra, [cv2.IMWRITE_PNG_COMPRESSION, 1])
        if not ok:
            raise RuntimeError("PNG encoding failed")
        return buf.tobytes()


def _ellipse(k: int) -> np.ndarray:
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))


def grow_mask(mask: np.ndarray, s: float = 1.0) -> np.ndarray:
    """Dilate the strokes and swallow the soft drop shadow down-right of them."""
    k = max(3, int(round(9 * s)) | 1)
    grown = cv2.dilate(mask, _ellipse(k))
    d = max(1, int(round(2 * s)))
    shifted = np.zeros_like(grown)
    shifted[d:, d:] = grown[:-d, :-d]
    return cv2.max(grown, shifted)


def estimate_background(bgr: np.ndarray, hole: np.ndarray) -> np.ndarray:
    """Fill `hole` (uint8 mask) by normalised convolution: blur(img*valid)/blur(valid).

    Uses the smallest sigma that has enough valid support at each pixel. The
    blurs run at half resolution (area-averaged, which keeps the normalised
    convolution exact); the estimate is smooth, so nothing visible is lost and
    it is several times faster.
    """
    h, w = hole.shape
    valid = (hole == 0).astype(np.float32)
    img = bgr.astype(np.float32) * valid[:, :, None]
    small = (max(1, w // 2), max(1, h // 2))
    img_s = cv2.resize(img, small, interpolation=cv2.INTER_AREA)
    valid_s = cv2.resize(valid, small, interpolation=cv2.INTER_AREA)
    est = np.zeros_like(img_s)
    todo = valid_s < 0.999
    for sigma in (1.25, 2.5, 5.0, 10.0):
        if not todo.any():
            break
        num = cv2.GaussianBlur(img_s, (0, 0), sigma)
        den = cv2.GaussianBlur(valid_s, (0, 0), sigma)
        good = todo & (den > 0.08)
        est[good] = num[good] / den[good][:, None]
        todo &= ~good
    if todo.any():  # a hole wider than every kernel: fall back to the mean of valid pixels
        est[todo] = img_s.sum(axis=(0, 1)) / max(1e-3, float(valid_s.sum()))
    up = cv2.resize(est, (w, h), interpolation=cv2.INTER_LINEAR)
    out = bgr.copy()
    sel = hole > 0
    out[sel] = np.clip(up[sel], 0, 255).astype(np.uint8)
    return out


def make_fill(frame_bgr: np.ndarray, block: Block, layer_id: str = "fill") -> RgbaLayer:
    """The stroke-only patch: background colour on the grown mask, transparent elsewhere."""
    s = frame_bgr.shape[0] / 1080.0
    crop = frame_bgr[block.y0 : block.y1, block.x0 : block.x1]
    hole = grow_mask(block.mask, s)
    bg = estimate_background(crop, hole)
    soft = cv2.GaussianBlur(hole, (0, 0), 0.8 * s)
    alpha = cv2.max(hole, soft)
    bgra = np.dstack([bg, alpha])
    bgra[alpha == 0] = 0  # colour under transparent pixels would double the PNG size
    return RgbaLayer(layer_id, block.x0, block.y0, bgra, z=0)


def stroke_color(frame_bgr: np.ndarray, block: Block) -> tuple[int, int, int]:
    """Colour of the cores of the English strokes (BGR)."""
    crop = frame_bgr[block.y0 : block.y1, block.x0 : block.x1]
    core = cv2.erode(block.mask, _ellipse(3))
    sel = crop[core > 0]
    if len(sel) < 20:
        sel = crop[block.mask > 0]
    if len(sel) == 0:
        return (241, 247, 242)
    b, g, r = np.median(sel, axis=0)
    return int(b), int(g), int(r)


def latin_metrics(block: Block) -> tuple[float, list[int]]:
    """(ascender height in px, baseline y per line in frame pixels) measured from the mask."""
    heights: list[int] = []
    baselines: list[int] = []
    for ln in block.lines:
        sub = block.mask[ln.y0 - block.y0 : ln.y1 - block.y0, ln.x0 - block.x0 : ln.x1 - block.x0]
        n, _, stats, _ = cv2.connectedComponentsWithStats(sub, connectivity=8)
        hs = [int(stats[i][3]) for i in range(1, n) if stats[i][4] >= 6]
        bottoms = [int(stats[i][1] + stats[i][3]) for i in range(1, n) if stats[i][4] >= 6]
        if not hs:
            heights.append(ln.y1 - ln.y0)
            baselines.append(ln.y1)
            continue
        # Most letters sit on the baseline; descenders (g, p, y) go below it.
        baseline = int(np.percentile(bottoms, 40))
        tall = [h for h, b in zip(hs, bottoms) if abs(b - baseline) <= 2]
        heights.append(int(np.percentile(tall or hs, 90)))
        baselines.append(ln.y0 + baseline)
    return float(np.median(heights)), baselines


def measured_size(block: Block, style: Style) -> int:
    """Font size that makes the alef as tall as this block's Latin ascenders."""
    asc, _ = latin_metrics(block)
    return arabic.size_for_alef(style.font, (asc + 1) * style.size_factor)


def _wrap(words: list[str], n_lines: int, measure) -> list[str]:
    """Split words into n_lines lines with the smallest possible widest line."""
    if n_lines <= 1 or len(words) <= 1:
        return [" ".join(words)]
    n_lines = min(n_lines, len(words))
    best: tuple[float, list[str]] | None = None

    def rec(start: int, left: int, acc: list[str]) -> None:
        nonlocal best
        if left == 1:
            lines = acc + [" ".join(words[start:])]
            width = max(measure(l) for l in lines)
            if best is None or width < best[0]:
                best = (width, lines)
            return
        for cut in range(start + 1, len(words) - left + 2):
            rec(cut, left - 1, acc + [" ".join(words[start:cut])])

    if len(words) > 14:  # keep the search small for very long lines: greedy by target width
        total = measure(" ".join(words))
        target = total / n_lines
        lines, cur = [], []
        for w in words:
            if cur and measure(" ".join(cur + [w])) > target * 1.05 and len(lines) < n_lines - 1:
                lines.append(" ".join(cur))
                cur = [w]
            else:
                cur.append(w)
        lines.append(" ".join(cur))
        return lines
    rec(0, n_lines, [])
    return best[1] if best else [" ".join(words)]


@dataclass
class TextLayout:
    lines: list[str]
    size: int
    baselines: list[int]  # frame pixels
    center_x: float
    width: float


def layout_text(text: str, block: Block, style: Style) -> TextLayout:
    asc, baselines = latin_metrics(block)
    size = style.fixed_size or measured_size(block, style)
    words = text.split()
    center_x = float(np.mean([(l.x0 + l.x1) / 2 for l in block.lines]))
    max_w = float(max(l.x1 - l.x0 for l in block.lines))
    pitch = baselines[1] - baselines[0] if len(baselines) > 1 else int(round(asc * 2.0))

    def fit(n_lines: int, sz: int) -> tuple[list[str], float]:
        lines = _wrap(words, n_lines, lambda t: arabic.line_width(t, sz, style.font))
        return lines, max(arabic.line_width(l, sz, style.font) for l in lines)

    n = len(block.lines)
    lines, width = fit(n, size)
    if style.fixed_size:
        max_w = max(max_w, float(style.min_wrap_width))
        while width > max_w and n < len(words) and n < 4:
            n += 1
            lines, width = fit(n, size)
    elif width > max_w:
        shrunk = max(int(np.ceil(size * style.max_shrink)), int(np.floor(size * max_w / width)))
        lines2, width2 = fit(n, shrunk)
        if width2 <= max_w:
            size, lines, width = shrunk, lines2, width2
        else:  # still too wide: add a line; it grows upward so the bottom baseline stays fixed
            while width > max_w and n < len(words) and n < 4:
                n += 1
                lines, width = fit(n, size)
    bottom = baselines[-1] + int(style.y_offset)
    out_baselines = [bottom - pitch * (len(lines) - 1 - i) for i in range(len(lines))]
    return TextLayout(lines, size, out_baselines, center_x, width)


def make_text(frame_bgr: np.ndarray, block: Block, text: str, style: Style = Style(), layer_id: str = "text") -> RgbaLayer:
    """Arabic glyphs with their drop shadow, centred on the English block."""
    layout = layout_text(text, block, style)
    color = style.color or stroke_color(frame_bgr, block)
    fh, fw = frame_bgr.shape[:2]
    parts = []
    for line, baseline in zip(layout.lines, layout.baselines):
        shaped = arabic.shape_line(line, layout.size, style.font)
        alpha, ox, oy = arabic.rasterize(shaped, layout.size)
        left = int(round(layout.center_x - shaped.width / 2.0)) - ox
        parts.append((left, baseline - oy, alpha))
    dx, dy = style.shadow_offset
    margin = int(np.ceil(3 * style.shadow_sigma)) + max(abs(dx), abs(dy)) + int(style.outline_px) + 2
    x0 = max(0, min(p[0] for p in parts) - margin)
    y0 = max(0, min(p[1] for p in parts) - margin)
    x1 = min(fw, max(p[0] + p[2].shape[1] for p in parts) + margin)
    y1 = min(fh, max(p[1] + p[2].shape[0] for p in parts) + margin)
    glyphs = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
    for left, top, alpha in parts:
        gx0, gy0 = max(left, x0), max(top, y0)
        gx1, gy1 = min(left + alpha.shape[1], x1), min(top + alpha.shape[0], y1)
        if gx1 <= gx0 or gy1 <= gy0:
            continue
        src = alpha[gy0 - top : gy1 - top, gx0 - left : gx1 - left]
        dst = glyphs[gy0 - y0 : gy1 - y0, gx0 - x0 : gx1 - x0]
        np.maximum(dst, src, out=dst)
    if style.effect == "outline":
        k = 2 * max(1, int(style.outline_px)) + 1
        edge = cv2.dilate(glyphs, _ellipse(k))
        shadow = cv2.GaussianBlur(edge, (0, 0), 0.7).astype(np.float32)
    elif style.effect == "none":
        shadow = np.zeros(glyphs.shape, np.float32)
    else:
        shadow = np.zeros_like(glyphs)
        shadow[max(0, dy) :, max(0, dx) :] = glyphs[: glyphs.shape[0] - max(0, dy), : glyphs.shape[1] - max(0, dx)]
        shadow = cv2.GaussianBlur(shadow, (0, 0), style.shadow_sigma).astype(np.float32) * style.shadow_opacity
    ga = glyphs.astype(np.float32) / 255.0
    sa = shadow / 255.0
    out_a = ga + sa * (1.0 - ga)  # glyphs over shadow (shadow is black)
    safe = np.maximum(out_a, 1e-6)
    bgra = np.zeros(glyphs.shape + (4,), dtype=np.uint8)
    for c in range(3):
        bgra[:, :, c] = np.clip(color[c] * ga / safe, 0, 255).astype(np.uint8)
    bgra[:, :, 3] = np.clip(out_a * 255.0, 0, 255).astype(np.uint8)
    bgra[bgra[:, :, 3] == 0] = 0
    return RgbaLayer(layer_id, x0, y0, bgra, z=2)


def make_plate(text: RgbaLayer, frame_shape, opacity: float = 0.62, layer_id: str = "plate",
               cover: tuple[int, int, int, int] | None = None) -> RgbaLayer:
    """`dim` plate: a feathered dark rounded box behind the Arabic. It does not
    depend on the picture, so it can never show stale pixels; it also hides
    whatever English appears underneath while the Arabic is held on screen."""
    fh, fw = frame_shape[:2]
    pad_x, pad_y, feather = 22, 8, 7
    x0, y0 = text.x - pad_x, text.y - pad_y
    x1, y1 = text.x + text.w + pad_x, text.y + text.h + pad_y
    if cover is not None:  # also hide this rectangle (the English line still on screen)
        x0, y0 = min(x0, cover[0] - 6), min(y0, cover[1] - 2)
        x1, y1 = max(x1, cover[2] + 6), max(y1, cover[3] + 2)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(fw, x1), min(fh, y1)
    w, h = x1 - x0, y1 - y0
    alpha = np.zeros((h, w), np.float32)
    m = feather * 2
    if w > 2 * m and h > 2 * m:
        cv2.rectangle(alpha, (m, m), (w - m - 1, h - m - 1), 1.0, -1)
    else:
        alpha[:] = 1.0
    alpha = cv2.GaussianBlur(alpha, (0, 0), feather)
    alpha = np.clip(alpha / max(1e-6, float(alpha.max())), 0.0, 1.0) * opacity
    bgra = np.zeros((h, w, 4), np.uint8)
    bgra[:, :, 3] = (alpha * 255).astype(np.uint8)
    return RgbaLayer(layer_id, x0, y0, bgra, z=1)


def composite(frame_bgr: np.ndarray, layers: list[RgbaLayer]) -> np.ndarray:
    """Draw layers over a frame the way the TV does (for previews and tests)."""
    out = frame_bgr.astype(np.float32).copy()
    for layer in sorted(layers, key=lambda l: l.z):
        region = out[layer.y : layer.y + layer.h, layer.x : layer.x + layer.w]
        a = layer.bgra[: region.shape[0], : region.shape[1], 3:4].astype(np.float32) / 255.0
        region[:] = layer.bgra[: region.shape[0], : region.shape[1], :3] * a + region * (1.0 - a)
    return np.clip(out, 0, 255).astype(np.uint8)
