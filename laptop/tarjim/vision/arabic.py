"""Arabic text shaping and rasterising with HarfBuzz + FreeType.

Pillow on this machine has no RAQM, so shaping is done here: split the line
into direction runs (a small bidi for subtitle lines: RTL base, LTR runs for
Latin words and numbers), pick a font that has every glyph of the run, shape
each run with HarfBuzz and rasterise the glyphs with FreeType.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import freetype
import numpy as np
import uharfbuzz as hb

from .. import paths

FONT_DIR = paths.REPO / "fonts"
FONT_FILES = {
    "harmattan": "Harmattan-Regular.ttf",
    "harmattan-bold": "Harmattan-Bold.ttf",
    "noto-naskh": "NotoNaskhArabic-VF.ttf",
    "noto-sans-arabic": "NotoSansArabic-VF.ttf",
    "noto-sans": "NotoSans-VF.ttf",
}
FALLBACKS = ["noto-naskh", "noto-sans"]


class FontError(Exception):
    pass


class Font:
    def __init__(self, path: Path) -> None:
        if not path.exists():
            raise FontError(f"font file missing: {path}")
        self.path = path
        data = path.read_bytes()
        self.ft = freetype.Face(str(path))
        self._hb_face = hb.Face(data)
        self._hb_fonts: dict[int, hb.Font] = {}
        self._size = 0

    def has(self, ch: str) -> bool:
        return self.ft.get_char_index(ord(ch)) != 0

    def hb_font(self, size: int) -> hb.Font:
        font = self._hb_fonts.get(size)
        if font is None:
            font = hb.Font(self._hb_face)
            font.scale = (size * 64, size * 64)
            self._hb_fonts[size] = font
        return font

    def set_size(self, size: int) -> None:
        if size != self._size:
            self.ft.set_pixel_sizes(0, size)
            self._size = size


@lru_cache(maxsize=None)
def load_font(name: str) -> Font:
    if name not in FONT_FILES:
        raise FontError(f"unknown font {name!r}")
    return Font(FONT_DIR / FONT_FILES[name])


# -- bidi ---------------------------------------------------------------------


def _strong(ch: str) -> str | None:
    """'R', 'L', 'N' (number) or None for neutral characters."""
    b = unicodedata.bidirectional(ch)
    if b in ("R", "AL"):
        return "R"
    if b == "L":
        return "L"
    if b in ("EN", "AN"):
        return "N"
    return None


def bidi_runs(text: str) -> list[tuple[str, str]]:
    """Split a line into (direction, text) runs in logical order; base direction RTL.

    Numbers form LTR runs. Neutrals (spaces, punctuation) between two LTR
    pieces stay LTR; every other neutral takes the RTL base direction.
    Number separators between digits stay with the number.
    """
    n = len(text)
    kinds = [_strong(c) for c in text]
    dirs: list[str | None] = [None] * n
    for i, k in enumerate(kinds):
        if k == "R":
            dirs[i] = "R"
        elif k in ("L", "N"):
            dirs[i] = "L"
        elif unicodedata.bidirectional(text[i]) == "NSM" and i > 0:
            dirs[i] = dirs[i - 1]
    i = 0
    while i < n:
        if dirs[i] is not None:
            i += 1
            continue
        j = i
        while j < n and dirs[j] is None:
            j += 1
        before = dirs[i - 1] if i > 0 else "R"
        after = dirs[j] if j < n else "R"
        fill = "L" if before == "L" and after == "L" else "R"
        if fill == "R" and before == "L" and after == "L":
            fill = "L"
        # "3.5", "10:30", "1,000": a single separator between two digits.
        if j - i == 1 and i > 0 and j < n and kinds[i - 1] == "N" and kinds[j] == "N":
            fill = "L"
        for k in range(i, j):
            dirs[k] = fill
        i = j
    runs: list[tuple[str, str]] = []
    start = 0
    for i in range(1, n + 1):
        if i == n or dirs[i] != dirs[start]:
            runs.append((dirs[start] or "R", text[start:i]))
            start = i
    return runs


# -- shaping ------------------------------------------------------------------


@dataclass
class Glyph:
    font: Font
    gid: int
    x: float  # pen position of the glyph origin, pixels from the line's left edge
    y: float  # offset above the baseline, pixels


@dataclass
class ShapedLine:
    glyphs: list[Glyph]
    width: float
    missing: int  # characters no font could draw


def _pick_fonts(text: str, fonts: list[Font]) -> list[tuple[Font, str]]:
    """Split a run so each piece is fully covered by one font (first match wins)."""
    pieces: list[tuple[Font, str]] = []
    current: Font | None = None
    buf = ""
    for ch in text:
        if ch.isspace() or unicodedata.category(ch) in ("Mn", "Cf"):
            chosen = current or fonts[0]  # spaces and marks stay with their neighbour
        else:
            chosen = next((f for f in fonts if f.has(ch)), fonts[0])
        if current is not None and chosen is not current:
            pieces.append((current, buf))
            buf = ""
        current = chosen
        buf += ch
    if buf and current is not None:
        pieces.append((current, buf))
    return pieces


def shape_line(text: str, size: int, font: str = "harmattan") -> ShapedLine:
    fonts = [load_font(font)] + [load_font(f) for f in FALLBACKS if f != font]
    glyphs: list[Glyph] = []
    missing = 0
    pen = 0.0
    for direction, run_text in reversed(bidi_runs(text)):  # visual order, left to right
        pieces = _pick_fonts(run_text, fonts)
        if direction == "R":
            pieces = list(reversed(pieces))
        for f, piece in pieces:
            buf = hb.Buffer()
            buf.add_str(piece)
            if direction == "R":
                buf.direction, buf.script, buf.language = "rtl", "Arab", "ar"
            else:
                buf.direction, buf.script, buf.language = "ltr", "Latn", "en"
            hb.shape(f.hb_font(size), buf, {"kern": True, "liga": True})
            for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
                if info.codepoint == 0:
                    missing += 1
                glyphs.append(Glyph(f, info.codepoint, pen + pos.x_offset / 64.0, pos.y_offset / 64.0))
                pen += pos.x_advance / 64.0
    return ShapedLine(glyphs, pen, missing)


def rasterize(line: ShapedLine, size: int, pad: int = 4) -> tuple[np.ndarray, int, int]:
    """Return (alpha uint8, x of the line's left edge, y of the baseline) inside the image."""
    boxes = []
    for g in line.glyphs:
        g.font.set_size(size)
        g.font.ft.load_glyph(g.gid, freetype.FT_LOAD_RENDER | freetype.FT_LOAD_NO_HINTING)
        slot = g.font.ft.glyph
        bmp = slot.bitmap
        if bmp.width == 0 or bmp.rows == 0:
            continue
        arr = np.array(bmp.buffer, dtype=np.uint8).reshape(bmp.rows, bmp.pitch)[:, : bmp.width]
        left = int(round(g.x)) + slot.bitmap_left
        top = -int(round(g.y)) - slot.bitmap_top  # relative to the baseline, y down
        boxes.append((left, top, arr))
    if not boxes:
        return np.zeros((1, 1), np.uint8), 0, 0
    x0 = min(0, min(b[0] for b in boxes)) - pad
    x1 = max(int(np.ceil(line.width)), max(b[0] + b[2].shape[1] for b in boxes)) + pad
    y0 = min(b[1] for b in boxes) - pad
    y1 = max(b[1] + b[2].shape[0] for b in boxes) + pad
    canvas = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
    for left, top, arr in boxes:
        ys, xs = top - y0, left - x0
        region = canvas[ys : ys + arr.shape[0], xs : xs + arr.shape[1]]
        np.maximum(region, arr, out=region)
    return canvas, -x0, -y0


@lru_cache(maxsize=64)
def alef_height(font: str, size: int) -> int:
    """Pixel height of the letter alef at this size: the yardstick for matching Latin ascenders."""
    alpha, _, _ = rasterize(shape_line("ا", size, font), size, pad=0)
    rows = np.where(alpha.max(axis=1) > 64)[0]
    return int(rows[-1] - rows[0] + 1) if len(rows) else size // 2


def size_for_alef(font: str, target_px: float) -> int:
    ref = alef_height(font, 100)
    size = max(8, int(round(100.0 * target_px / ref)))
    while alef_height(font, size) > target_px and size > 8:
        size -= 1
    while alef_height(font, size + 1) <= target_px:
        size += 1
    return size
