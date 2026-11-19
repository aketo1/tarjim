"""Screen text in Arabic: menus, the phone's messages, prompts and notices (GTA VI only).

Runs beside the subtitles on its own thread, so subtitles keep their speed: the frame loop
only hands over the newest picture (`feed`). About eight times a second the screen is
searched (vision/screen.py); a text that stays put for two searches is read, translated and
drawn back in its own place:

  - in its own size (the Arabic alef as tall as the English capitals),
  - in its own colour, with the English hidden under the colour around it,
  - left-aligned where the English was (menus: the icon stays on its left), right-aligned for
    prompts and notices (the button stays on their right), and a message as a right-aligned
    Arabic paragraph on the card's own colour, the sender's name and picture left as they are.

Screen words come from the game's own table first (gta6.UI: no waiting for the engine), and
the engine is asked only when the subtitles are not using it. Everything is drawn in the TV's
second window ("B"), whose four layers the subtitles never use; a TV without it gets one layer
in window A. Every layer has the usual time-to-live, so nothing stays up if this stops.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from . import protocol as P
from .tvlink import TvLinkError, now_ms
from .vision import arabic, render
from .vision.screen import Cand, FindParams, Item, Zone, build_item, cand_iou, cover, find_all

SEARCH_MS = 120  # time between two searches of the screen
SETTLE_SEARCHES = 2  # a text must be found this many times in a row before it is read
GONE_SEARCHES = 2  # ... and missed this many times before its Arabic is taken away
REFRESH_MS = 200  # the cover of text over the moving scene is redone this often
KEEP_MS = 250  # keep-alive for the layers (their time-to-live is 700 ms)
READ_BUDGET_MS = 180  # reading per search; what is left waits for the next one
MIDDLE_READS = 2  # at most this many reads per search in a zone of known words only
HOLD_WHOLE_MS = 400  # a part of the screen waits this long at most for its other words
OCR_BUDGET_MS = 120  # reading (without translating) per search
_LATER = object()  # a text only the engine can translate, left for the engine's turn
ENGINE_WAIT_MS = 400  # how long screen text waits for the subtitles to free the engine
LAYER_TTL_MS = 700
FONT = "noto-sans-arabic"
SIZE_FACTOR = 0.92  # the alef as tall as this share of the English capitals
MIN_SCORE = 0.70
SIG_SAME = 16.0  # mean difference of two small grey pictures of a text that did not change
SIG_CHANGED = 32.0  # ... and of one that surely did (it goes at once)
SIG_MOVING = 45.0  # the same over the moving scene (a prompt beside a person)
INK_STILL = 6.0  # letters whose brightness changed less than this between two searches stopped fading


def _sig(frame: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    """A small grey picture of a box: cheap to compare from one search to the next."""
    x0, y0, x1, y1 = box
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(frame.shape[1], x1), min(frame.shape[0], y1)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return np.zeros((8, 32), np.float32)
    g = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    return cv2.resize(g, (32, 8), interpolation=cv2.INTER_AREA).astype(np.float32)


def _diff(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(a - b).mean())


# The picture around a text counts as still when it changed less than this between two searches.
# A cover made from the stream matches the TV's picture only while nothing moves: the stream
# lags the TV, so over a moving scene it shows as a smudge.
STILL_MAX = 6.0


def _ring(item: Item, fw: int, fh: int) -> tuple[int, int, int, int]:
    """The picture around a text: its box grown by about one letter height."""
    g = max(6, int(item.cap))
    return max(0, item.x0 - g), max(0, item.y0 - g), min(fw, item.x1 + g), min(fh, item.y1 + g)


def still_around(prev: np.ndarray | None, frame: np.ndarray, item: Item) -> bool:
    """True when the picture around the text did not move since the previous search."""
    if prev is None or prev.shape != frame.shape:
        return False
    box = _ring(item, frame.shape[1], frame.shape[0])
    return _diff(_sig(prev, box), _sig(frame, box)) <= STILL_MAX


def _ink_level(frame: np.ndarray, cand: Cand) -> float:
    """The letters' brightness: the brightest few pixels of light text, the darkest of dark."""
    x0, y0, x1, y1 = cand.box
    x0, y0 = max(0, x0), max(0, y0)
    crop = frame[y0:max(y0 + 1, y1):2, x0:max(x0 + 1, x1):2]
    if crop.size == 0:
        return 0.0
    if cand.dark:
        return float(np.percentile(crop.max(axis=2), 5))
    return float(np.percentile(crop.min(axis=2), 95))


@dataclass
class _Track:
    cand: Cand
    sig: np.ndarray
    first: float
    seen: int = 1
    misses: int = 0
    state: str = "wait"  # wait, read (waits for the engine), shown, rejected, skipped
    item: Item | None = None
    english: str = ""
    arabic: str = ""
    flat: bool = True  # on an even ground: its cover never needs redoing
    patches: list[render.RgbaLayer] = field(default_factory=list)  # cover and text, frame pixels
    version: int = 0  # raised each time its cover is redone
    shown_at: float = 0.0  # when its Arabic was ready
    score: float = 0.0  # the reader's confidence
    ocr_ms: float = 0.0
    ink: float = 0.0  # how light (or dark) its letters are: it changes while a menu fades

    @property
    def card(self) -> bool:
        return self.cand.panel_bgr is not None


def outlined_light(item: Item) -> bool:
    """True when the dark strokes are only the edges of light letters: they close around holes
    as tall as a letter. A real message's letters close only around small holes (o, e, a); the
    light gaps between its letters are open above and below."""
    free = (item.mask == 0).astype(np.uint8)
    n, _lab, stats, _ = cv2.connectedComponentsWithStats(free, connectivity=4)
    H, W = free.shape
    cap = item.cap
    holes = 0
    for i in range(1, n):
        x, y, w, h, _a = (int(v) for v in stats[i])
        if x > 0 and y > 0 and x + w < W and y + h < H and h >= 0.6 * cap:
            holes += 1
    return holes >= 3


def looks_like_words(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 2:
        return False
    if sum(1 for c in letters if c.isascii()) < 0.8 * len(letters):
        return False
    words = [w for w in text.split() if sum(ch.isalpha() for ch in w) >= 2]
    if not words:
        return False
    signs = sum(1 for c in text if not (c.isalnum() or c.isspace()))
    return signs <= max(2, 0.25 * len(text))


# -- drawing --------------------------------------------------------------------------------


def _ink(frame: np.ndarray, item: Item) -> tuple[int, int, int]:
    """The colour of the English letters (their cores), BGR."""
    crop = frame[item.y0:item.y1, item.x0:item.x1]
    core = cv2.erode(item.mask, np.ones((2, 2), np.uint8))
    sel = crop[core > 0]
    if len(sel) < 10:
        sel = crop[item.mask > 0]
    if len(sel) == 0:
        return (40, 40, 40) if item.dark else (245, 245, 245)
    b, g, r = np.median(sel[:: max(1, len(sel) // 300)], axis=0)
    return int(b), int(g), int(r)


def _even_ground(frame: np.ndarray, item: Item, limit: float = 3.5) -> bool:
    """A panel, not the scene: the ground around the letters changes slowly. A selected row that
    fades from white to the panel's colour is even too: what counts is how much neighbouring
    pixels differ, not how far the two ends of the row are apart."""
    crop = frame[item.y0:item.y1, item.x0:item.x1].astype(np.float32)
    grown = cv2.dilate(item.mask, np.ones((7, 7), np.uint8))
    free = (grown == 0)
    if free.sum() < 12:
        return False
    gray = crop.mean(axis=2)
    dx = np.abs(np.diff(gray, axis=1))[free[:, 1:] & free[:, :-1]]
    dy = np.abs(np.diff(gray, axis=0))[free[1:, :] & free[:-1, :]]
    rough = np.concatenate([dx, dy])
    # a panel is smooth (a blurred backdrop too); sand or a wall in the sun is not
    return bool(len(rough) >= 8 and float(np.percentile(rough, 90)) < limit)


def _wrap(words: list[str], width: float, size: int) -> list[str]:
    lines: list[str] = []
    cur: list[str] = []
    for w in words:
        trial = " ".join(cur + [w])
        if cur and arabic.line_width(trial, size, FONT) > width:
            lines.append(" ".join(cur))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(" ".join(cur))
    return lines


def _text_patch(lines: list[str], size: int, baselines: list[int], anchor_x: float, align: str,
                color: tuple[int, int, int], edge: str, fw: int, fh: int) -> render.RgbaLayer | None:
    """Arabic lines placed by their baselines; anchor_x is their left edge ("left") or right edge."""
    parts = []
    for line, base in zip(lines, baselines):
        shaped = arabic.shape_line(line, size, FONT)
        alpha, ox, oy = arabic.rasterize(shaped, size)
        if align == "left":
            left = int(round(anchor_x)) - ox
        elif align == "center":
            left = int(round(anchor_x - shaped.width / 2.0)) - ox
        else:
            left = int(round(anchor_x - shaped.width)) - ox
        parts.append((left, base - oy, alpha))
    if not parts:
        return None
    m = 6 if edge != "none" else 2
    x0 = max(0, min(p[0] for p in parts) - m)
    y0 = max(0, min(p[1] for p in parts) - m)
    x1 = min(fw, max(p[0] + p[2].shape[1] for p in parts) + m)
    y1 = min(fh, max(p[1] + p[2].shape[0] for p in parts) + m)
    if x1 <= x0 or y1 <= y0:
        return None
    glyphs = np.zeros((y1 - y0, x1 - x0), np.uint8)
    for left, top, alpha in parts:
        gx0, gy0 = max(left, x0), max(top, y0)
        gx1, gy1 = min(left + alpha.shape[1], x1), min(top + alpha.shape[0], y1)
        if gx1 > gx0 and gy1 > gy0:
            dst = glyphs[gy0 - y0:gy1 - y0, gx0 - x0:gx1 - x0]
            np.maximum(dst, alpha[gy0 - top:gy1 - top, gx0 - left:gx1 - left], out=dst)
    ga = glyphs.astype(np.float32) / 255.0
    if edge == "edge":
        # The game's prompts over the scene are white with a thin dark edge all round: the
        # Arabic gets the same, so it reads on bright sand as well as on a dark street.
        rim = cv2.dilate(glyphs, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
        sh = cv2.GaussianBlur(rim, (0, 0), 0.9).astype(np.float32) / 255.0
        sa = np.clip(sh * 1.1, 0, 0.92)
    else:
        sa = np.zeros_like(ga)
    out_a = ga + sa * (1.0 - ga)
    ratio = ga / np.maximum(out_a, 1e-6)
    bgra = np.empty(glyphs.shape + (4,), np.uint8)
    for c in range(3):
        bgra[:, :, c] = (color[c] * ratio).astype(np.uint8)
    bgra[:, :, 3] = np.clip(out_a * 255.0, 0, 255).astype(np.uint8)
    return render.RgbaLayer("t", x0, y0, bgra, z=2)


def _flat_cover(item: Item, fw: int, fh: int) -> render.RgbaLayer:
    """The card's own colour over its English paragraph, with soft edges."""
    pad = max(3, int(0.35 * item.cap))
    x0, y0 = max(0, min(l.x0 for l in item.lines) - pad), max(0, min(l.y0 for l in item.lines) - pad)
    x1 = min(fw, max(l.x1 for l in item.lines) + pad)
    y1 = min(fh, max(l.y1 for l in item.lines) + 2 * pad)  # room for the tails of g, p, y
    a = np.zeros((y1 - y0, x1 - x0), np.float32)
    f = 2
    a[f:-f or None, f:-f or None] = 1.0
    a = cv2.GaussianBlur(a, (0, 0), 1.0)
    bgra = np.zeros((y1 - y0, x1 - x0, 4), np.uint8)
    bgra[:, :, :3] = item.panel_bgr
    bgra[:, :, 3] = np.clip(a * 255, 0, 255).astype(np.uint8)
    return render.RgbaLayer("c", x0, y0, bgra, z=0)


def _box_cover(frame: np.ndarray, item: Item) -> render.RgbaLayer:
    """On an even ground (a menu panel, a selected row): the whole text box is covered with the
    ground around it, carried across it the way it runs (a row that fades left to right keeps
    fading). No trace of a letter can be left, whatever the strokes found missed."""
    fh, fw = frame.shape[:2]
    cap = item.cap
    pad = max(3, int(0.30 * cap))
    hx0, hy0 = max(0, min(l.x0 for l in item.lines) - pad), max(0, min(l.y0 for l in item.lines) - pad)
    if item.hard_x0 is not None:
        hx0 = max(hx0, item.hard_x0)  # the menu's icon stays untouched
    hx1 = min(fw, max(l.x1 for l in item.lines) + pad)
    hy1 = min(fh, max(l.y1 for l in item.lines) + pad)
    if item.icon_l is not None:  # an icon or a button beside the words stays untouched
        hx0 = max(hx0, item.icon_l + 1)
    if item.icon_r is not None:
        hx1 = min(hx1, item.icon_r - 1)
    ring = max(4, int(0.5 * cap))
    rx0, ry0, rx1, ry1 = max(0, hx0 - ring), max(0, hy0 - ring), min(fw, hx1 + ring), min(fh, hy1 + ring)
    crop = np.ascontiguousarray(frame[ry0:ry1, rx0:rx1])
    hole = np.zeros(crop.shape[:2], np.uint8)
    hole[hy0 - ry0:hy1 - ry0, hx0 - rx0:hx1 - rx0] = 255
    # strokes of other text in the ring (a neighbour, an icon) do not count as ground
    hole = cv2.max(hole, cv2.dilate(_strokes_any(crop), np.ones((5, 5), np.uint8)))
    bg = render.estimate_background(crop, hole)
    alpha = np.zeros(crop.shape[:2], np.float32)
    alpha[hy0 - ry0:hy1 - ry0, hx0 - rx0:hx1 - rx0] = 1.0
    # soft edges: the ground carried across is never exact, a seam would show as a box
    alpha = cv2.GaussianBlur(alpha, (0, 0), max(1.2, 0.15 * cap))
    alpha = np.clip(alpha * 1.6, 0.0, 1.0)  # still fully opaque over the letters themselves
    if item.hard_x0 is not None:
        alpha[:, :max(0, item.hard_x0 - rx0)] = 0.0  # not even the soft edge reaches the icon
    bgra = cv2.cvtColor(bg, cv2.COLOR_BGR2BGRA)
    bgra[:, :, 3] = np.clip(alpha * 255, 0, 255).astype(np.uint8)
    return render.RgbaLayer("c", rx0, ry0, bgra, z=0)


def _strokes_any(crop: np.ndarray) -> np.ndarray:
    from .vision.screen import strokes as _st

    p = FindParams()
    s = 1.0
    return cv2.max(_st(crop, True, p, s), _st(crop, False, p, s))


def _stroke_cover(frame: np.ndarray, item: Item) -> render.RgbaLayer:
    """Over the moving scene: only the letters (grown well past their soft edges) are covered."""
    crop = np.ascontiguousarray(frame[item.y0:item.y1, item.x0:item.x1])
    # grown well past the letters: their dark edge goes too, not only the white inside it
    k = max(7, int(round(0.5 * item.cap)) | 1)
    hole = cv2.dilate(item.mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    for lim, keep_left in ((item.icon_l, True), (item.icon_r, False)):  # icons stay untouched
        if lim is not None:
            c = lim - item.x0
            if keep_left:
                hole[:, :max(0, c)] = 0
            else:
                hole[:, max(0, c):] = 0
    bg = render.estimate_background(crop, hole)
    alpha = cv2.max(hole, cv2.GaussianBlur(hole, (0, 0), 1.0))
    bg[alpha == 0] = 0
    bgra = cv2.cvtColor(bg, cv2.COLOR_BGR2BGRA)
    bgra[:, :, 3] = alpha
    return render.RgbaLayer("c", item.x0, item.y0, bgra, z=0)


def _edge(item: Item, flat: bool) -> str:
    """How the Arabic is set off from what is behind it: light letters over the scene get the
    dark edge the game's own prompts have; on a panel nothing is needed."""
    if item.dark or flat:
        return "none"
    return "edge"


def _single_line(item: Item, text: str, size: int, color, flat: bool, fw: int, fh: int):
    """One line, placed so it grows away from the item's icons and never runs over them."""
    ln = item.lines[0]
    en_w = ln.x1 - ln.x0
    gap = 0.3 * item.cap
    left_lim = None if item.icon_l is None else item.icon_l + gap
    right_lim = None if item.icon_r is None else item.icon_r - gap
    align = item.align
    if align == "center" and left_lim is not None and right_lim is not None:
        room = right_lim - left_lim
        anchor = (left_lim + right_lim) / 2.0
    elif align == "left":
        anchor = float(ln.x0)
        room = (right_lim - anchor) if right_lim is not None else max(en_w * 1.8, en_w + 4 * item.cap)
    elif align == "right":
        anchor = float(ln.x1)
        room = (anchor - left_lim) if left_lim is not None else max(en_w * 1.8, en_w + 4 * item.cap)
    else:
        anchor = (ln.x0 + ln.x1) / 2.0
        room = max(en_w * 1.8, en_w + 4 * item.cap)
    w = arabic.line_width(text, size, FONT)
    if w > room > 0:
        size = max(int(size * 0.65), int(size * room / w))
        w = arabic.line_width(text, size, FONT)
    # never off the screen: a title at the top left grows to the right instead
    left = {"left": anchor, "center": anchor - w / 2.0}.get(align, anchor - w)
    if left < 6:
        anchor, align = 6.0, "left"
    elif left + w > fw - 6:
        anchor, align = float(fw - 6), "right"
    baseline = ln.y0 + item.cap
    return _text_patch([text], size, [baseline], anchor, align, color, _edge(item, flat), fw, fh)


def draw_item(frame: np.ndarray, item: Item, text: str) -> tuple[list[render.RgbaLayer], bool]:
    """Cover and Arabic for one item, in frame pixels. Returns (patches, cover is on even ground)."""
    fh, fw = frame.shape[:2]
    color = _ink(frame, item)
    # A paragraph sits on a box (a hint box, a mission's notes): its whole box is covered when
    # its ground is calm enough, so a short word the search missed cannot show through.
    flat = item.panel_bgr is not None or _even_ground(frame, item, 7.0 if len(item.lines) > 1 else 3.5)
    if item.panel_bgr is not None:
        cover = _flat_cover(item, fw, fh)
    elif flat:
        cover = _box_cover(frame, item)
    else:
        cover = _stroke_cover(frame, item)
    # Arabic letters look larger than Latin ones of the same alef height: a little under it
    size = arabic.size_for_alef(FONT, SIZE_FACTOR * item.cap + 1)
    lines_en = item.lines
    words = text.split()
    if len(lines_en) > 1:
        # A paragraph: as wide as the English, right-aligned, its lines at the English pitch.
        width = float(max(l.x1 for l in lines_en) - min(l.x0 for l in lines_en))
        pitch = (lines_en[-1].y0 - lines_en[0].y0) / (len(lines_en) - 1)
        room = len(lines_en)
        lines = _wrap(words, width, size)
        while len(lines) > room and size > 0.7 * arabic.size_for_alef(FONT, SIZE_FACTOR * item.cap + 1):
            size -= 1
            lines = _wrap(words, width, size)
        if len(lines) > room:
            lines = lines[:room]
            lines[-1] = lines[-1].rstrip(".،") + "…"
        top = lines_en[0].y0
        baselines = [int(round(top + item.cap + k * pitch)) for k in range(len(lines))]
        # A message's paragraph reads right to left from the card's right; a heading in a
        # left-hand list keeps the list's left edge.
        if item.align == "left" and item.panel_bgr is None:
            anchor, align = float(min(l.x0 for l in lines_en)), "left"
        else:
            anchor, align = float(max(l.x1 for l in lines_en)), "right"
        patch = _text_patch(lines, size, baselines, anchor, align, color, _edge(item, flat), fw, fh)
    else:
        patch = _single_line(item, text, size, color, flat, fw, fh)
    out = [cover]
    if patch is not None:
        out.append(patch)
    return out, flat


def compose(patches: list[render.RgbaLayer], layer_id: str, z: int = 0) -> render.RgbaLayer | None:
    """One layer from many patches, drawn in order (covers first, then text)."""
    if not patches:
        return None
    x0, y0 = min(p.x for p in patches), min(p.y for p in patches)
    x1, y1 = max(p.x + p.w for p in patches), max(p.y + p.h for p in patches)
    # Colours are summed premultiplied by their alpha and divided back at the end: the TV draws
    # plain (straight) alpha, and premultiplied edges would show as a dark rim.
    canvas = np.zeros((y1 - y0, x1 - x0, 4), np.float32)
    for p in sorted(patches, key=lambda q: q.z):
        region = canvas[p.y - y0:p.y - y0 + p.h, p.x - x0:p.x - x0 + p.w]
        a = p.bgra[:, :, 3:4].astype(np.float32) / 255.0
        region[:, :, :3] = p.bgra[:, :, :3] * a + region[:, :, :3] * (1.0 - a)
        region[:, :, 3:4] = a + region[:, :, 3:4] * (1.0 - a)
    alpha = canvas[:, :, 3:4]
    out = np.empty(canvas.shape, np.uint8)
    out[:, :, :3] = np.clip(canvas[:, :, :3] / np.maximum(alpha, 1e-6), 0, 255).astype(np.uint8)
    out[:, :, 3] = np.clip(alpha[:, :, 0] * 255.0, 0, 255).astype(np.uint8)
    out[out[:, :, 3] == 0, :3] = 0  # keeps the PNG small
    return render.RgbaLayer(layer_id, x0, y0, out, z=z)


def pack_layers(tracks: list[_Track], slots: int) -> dict[str, list[_Track]]:
    """Texts grouped into at most `slots` layers, each at most 480 px tall (the TV's limit).
    Left and right of the screen are packed apart, top to bottom."""
    sides: dict[str, list[_Track]] = {"l": [], "r": []}
    for t in tracks:
        left = t.cand.align == "left" or (t.cand.align == "center" and t.cand.box[0] < 960)
        sides["l" if left and not t.card else "r"].append(t)
    chunks: list[list[_Track]] = []
    for ts in sides.values():
        cur: list[_Track] = []
        top = 0
        for t in sorted(ts, key=lambda t: min(p.y for p in t.patches)):
            t_top = min(p.y for p in t.patches)
            t_bot = max(p.y + p.h for p in t.patches)
            if cur and t_bot - top > P.MAX_LAYER_H:
                chunks.append(cur)
                cur = []
            if not cur:
                top = t_top
            cur.append(t)
        if cur:
            chunks.append(cur)
    if len(chunks) > slots:  # rare: keep the largest groups
        chunks = sorted(chunks, key=lambda c: -sum(p.w * p.h for t in c for p in t.patches))[:slots]
    return {f"ui{k}": c for k, c in enumerate(chunks)}


def attach(pipe, translator, ocr) -> "ScreenText":
    """Screen text for GTA VI beside a running pipeline: its own thread, translator and reader.
    The subtitles are not changed in any way: not where they are looked for, not what they read."""
    from . import gta6

    zones = tuple(Zone(*z) for z in gta6.ZONES)
    st = ScreenText(pipe.link, translator, ocr, zones, busy=lambda: pipe.busy, log=pipe.log_record,
                    exclude=(gta6.SUBTITLE_KEEP_OUT,), game=gta6)  # the subtitles' place is theirs alone
    pipe.screen = st
    return st


# -- the thread -----------------------------------------------------------------------------


class ScreenText:
    def __init__(self, link, translator, ocr, zones: tuple[Zone, ...], *, busy=None, log=None,
                 params: FindParams | None = None, exclude: tuple[dict, ...] = (), game=None) -> None:
        self.link = link
        self.translator = translator
        self.game = game  # the game's own screen words (gta6.py), or None
        self.ocr = ocr
        self.zones = zones
        self.exclude = exclude  # regions (fractions) left to the subtitles, never searched here
        self._known_only = {z.name for z in zones if z.known_only}  # zones that draw table words only
        self.params = params or FindParams()
        self.busy = busy or (lambda: False)  # True while the subtitles use the engine
        self.log = log  # callback(dict) for the session log
        self.enabled = True
        self.wanted = True  # the profile's switch; `enabled` is also off while the pipeline is
        self.window = "B"
        self.slots = 4
        self.shown_ms: list[float] = []  # first seen -> sent, per text
        self._tracks: list[_Track] = []
        self._frame: np.ndarray | None = None
        self._fresh = False
        self._cv = threading.Condition()
        self._stop = False
        self._sent: dict[str, tuple] = {}  # layer id -> what it holds (to send only changes)
        self._last_search = 0.0
        self._last_refresh = 0.0
        self._prev_frame = None  # the picture of the previous search: is the scene still?
        self._refresh_frame = None
        self._last_keep = 0.0
        self._memo: dict[str, str | None] = {}  # English -> Arabic (None: not drawn)
        self._shape = (1080, 1920)
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, name="tarjim-screen", daemon=True)
        self._thread.start()

    # -- from the frame loop ----------------------------------------------------------------

    def feed(self, frame: np.ndarray) -> None:
        with self._cv:
            self._frame = frame
            self._fresh = True
            self._cv.notify()

    def tick(self) -> None:
        """Keep the layers alive while this thread is busy reading (called by the frame loop)."""
        now = now_ms()
        with self._lock:
            ids = [k for k in self._sent]
        if ids and now - self._last_keep >= KEEP_MS:
            self._last_keep = now
            try:
                self.link.keep(ids)
            except TvLinkError:
                pass

    def set_enabled(self, on: bool) -> None:
        self.enabled = on
        if not on:
            self._clear_all()

    def close(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify()
        self._thread.join(timeout=2.0)
        self._clear_all()

    # -- the loop ---------------------------------------------------------------------------

    def _loop(self) -> None:
        while True:
            with self._cv:
                while not self._fresh and not self._stop:
                    self._cv.wait(0.2)
                if self._stop:
                    return
                frame = self._frame
                self._fresh = False
            if frame is None or not self.enabled:
                continue
            try:
                self.step(frame)
            except TvLinkError:
                with self._lock:
                    self._sent.clear()
            except Exception:
                pass  # a bad picture must not stop screen text for the rest of the session

    def _choose_window(self) -> None:
        wins = (getattr(self.link, "caps", {}) or {}).get("windows") or ["A"]
        if "B" in wins:
            self.window, self.slots = "B", 4
        else:
            self.window, self.slots = "A", 1  # the subtitles use three of window A's four layers

    def step(self, frame: np.ndarray, now: float | None = None) -> None:
        """One turn: search (if due), read what has settled, draw and send what changed."""
        now = now_ms() if now is None else now
        self._shape = frame.shape[:2]
        if now - self._last_search >= SEARCH_MS:
            self._last_search = now
            self._search(frame, now)
            self._read(frame, now)
            self._prev_frame = frame
        changed = self._redraw_moving(frame, now)
        self._send(changed, now)

    # -- searching and tracking ----------------------------------------------------------------

    def _search(self, frame: np.ndarray, now: float) -> None:
        fh, fw = frame.shape[:2]
        exclude = tuple((int(r["left"] * fw), int(r["top"] * fh), int(r["right"] * fw), int(r["bottom"] * fh))
                        for r in self.exclude)
        cands = find_all(frame, self.zones, self.params, exclude=exclude)
        used: set[int] = set()
        fresh: list[_Track] = []
        for t in self._tracks:
            best, best_iou = None, 0.0
            for i, c in enumerate(cands):
                if i in used or c.zone != t.cand.zone or c.dark != t.cand.dark or (c.panel_bgr is None) != (not t.card):
                    continue
                iou = cand_iou(c, t.cand)
                if iou > best_iou:
                    best, best_iou = i, iou
            sig_now = _sig(frame, t.cand.box)
            # Over the moving scene the picture around a prompt changes all the time: its
            # place and size say more than its picture there.
            same = SIG_SAME if t.flat else SIG_MOVING
            if best is not None and best_iou >= 0.5:
                d = _diff(sig_now, t.sig)
                if d <= same or (t.state == "wait" and d <= SIG_CHANGED):
                    used.add(best)
                    t.misses = 0
                    if t.state == "wait":
                        # Only letters that have stopped fading count towards being read: a menu
                        # fading in or out is read once it is fully there, never half-way. (The
                        # letters' own brightness, not the picture's: the scene behind a prompt moves.)
                        ink = _ink_level(frame, cands[best])
                        t.seen = t.seen + 1 if abs(ink - t.ink) <= INK_STILL else 1
                        t.cand, t.sig, t.ink = cands[best], sig_now, ink
                    else:
                        # Letters starting to fade out (a menu closing): their Arabic goes now.
                        if abs(_ink_level(frame, cands[best]) - t.ink) > 2 * INK_STILL:
                            used.add(best)
                            continue
                        t.seen += 1
                    fresh.append(t)
                    continue
            # Not found again, or found but changed: a text that surely changed goes at once.
            t.misses += 1
            if _diff(sig_now, t.sig) <= same and t.misses < GONE_SEARCHES and t.state != "wait":
                fresh.append(t)
        for i, c in enumerate(cands):
            if i not in used:
                fresh.append(_Track(c, _sig(frame, c.box), now, ink=_ink_level(frame, c)))
        with self._lock:
            self._tracks = fresh

    # -- reading --------------------------------------------------------------------------------

    def _read(self, frame: np.ndarray, now: float) -> None:
        """Read first, translate after: reading is quick (about 10 ms a text) and most screen
        words are in the game's table, so a busy screen (a magazine page full of headlines for
        the engine) never keeps its prompts and menus waiting."""
        t0 = time.perf_counter()
        # Messages first: what they decide settles the rows that overlap them; the middle last.
        ready = sorted((t for t in self._tracks if t.state == "wait" and t.seen >= SETTLE_SEARCHES),
                       key=lambda t: (not t.card, t.cand.zone in self._known_only, t.first, t.cand.box[2] - t.cand.box[0]))
        # Every part of the screen gets its turn: one text from each in rotation, so the scene's
        # letter-like rows on one side never keep a prompt on the other side waiting.
        by_zone: dict[str, list[_Track]] = {}
        for t in ready:
            by_zone.setdefault("card" if t.card else t.cand.zone, []).append(t)
        # Prompts and messages first: they are what a player acts on, and rarely the scene.
        first = ("card", "prompts", "right", "left")
        queues = [by_zone[z] for z in sorted(by_zone, key=lambda z: first.index(z) if z in first else len(first))]
        waiting = []
        while any(queues):
            for q in queues:
                if q:
                    waiting.append(q.pop(0))
        busy_reads = 0
        for t in waiting:
            if (time.perf_counter() - t0) * 1000.0 > OCR_BUDGET_MS:
                break
            if self._covered(t):
                t.state = "skipped"
                continue
            if t.cand.zone in self._known_only:
                # The scene there makes many letter-like rows; a few are read each turn.
                if busy_reads >= MIDDLE_READS:
                    continue
                busy_reads += 1
            self._ocr_one(frame, t)
        # The table's words at once, all of them; then the engine while the turn lasts.
        for engine in (False, True):
            for t in [t for t in self._tracks if t.state == "read"]:
                if engine and (time.perf_counter() - t0) * 1000.0 > READ_BUDGET_MS:
                    return
                if not self._covered(t):
                    self._finish_one(frame, t, now, engine)
                else:
                    t.state = "skipped"

    def _covered(self, t: _Track) -> bool:
        """A row inside a message that was read: the message speaks for it."""
        if t.card:
            return False
        return any(o.card and o.state == "shown" and cover(t.cand.box, o.cand.box) > 0.3 for o in self._tracks)

    def _ocr_one(self, frame: np.ndarray, t: _Track) -> None:
        item = build_item(frame, t.cand, self.params)
        if item is None or (t.card and outlined_light(item)):
            # White letters with a dark edge (a prompt, a subtitle) over a bright scene look like
            # a message from their edges; their light letters are read on their own instead.
            t.state = "rejected"
            return
        t_ocr = time.perf_counter()
        try:
            read = self.ocr.read(frame, item.block())
        except Exception:  # a sliver too small to read: skip it, never the whole turn
            t.state = "rejected"
            return
        t.ocr_ms = (time.perf_counter() - t_ocr) * 1000.0
        text = read.text.strip()
        if read.score < MIN_SCORE or not looks_like_words(text):
            t.state = "rejected"
            return
        if t.card and not t.cand.head and not any(c.islower() for c in text):
            # Capitals only: the white prompts with a dark edge, not a message. Their own
            # light letters are read as prompts.
            t.state = "rejected"
            return
        t.item, t.english, t.score, t.state = item, text, read.score, "read"

    def _finish_one(self, frame: np.ndarray, t: _Track, now: float, engine: bool) -> None:
        """Translate a read text and draw it; without `engine`, only what needs no engine."""
        text, item = t.english, t.item
        t_mt = time.perf_counter()
        ar = self._arabic(text, head=t.cand.head, known_only=t.cand.zone in self._known_only, engine=engine)
        mt_ms = (time.perf_counter() - t_mt) * 1000.0
        if ar is _LATER:
            return  # the engine's turn comes
        if not ar:
            t.state = "rejected"
            return
        ocr_ms = t.ocr_ms
        t.arabic = ar
        self._limit_by_neighbours(t, item)
        t.patches, t.flat = draw_item(frame, item, ar)
        if not t.flat and not still_around(self._prev_frame, frame, item):
            # Over a moving scene a cover is made from the stream, which lags the TV's own
            # picture: it shows as a smudge. Such a text stays in English (it is tried again
            # if the picture stops).
            t.state, t.patches = "read", []
            return
        t.state = "shown"
        t.shown_at = now
        self.shown_ms.append(now_ms() - t.first)
        if self.log is not None:
            self.log({"ui": t.cand.zone, "en": text, "ar": ar, "ocr_score": round(t.score, 3),
                      "ocr_ms": round(ocr_ms, 1), "mt_ms": round(mt_ms, 1), "card": t.card,
                      "first_ms": round(now_ms() - t.first, 1)})
        if t.card:  # rows the message covers are no longer read on their own
            for o in self._tracks:
                if o is not t and not o.card and cover(o.cand.box, t.cand.box) > 0.3:
                    o.state, o.patches = "skipped", []

    def _limit_by_neighbours(self, t: _Track, item: Item) -> None:
        """A word's Arabic may grow only up to the next text on its line (a row of tabs: a
        longer word would run into its neighbour). The neighbour counts like an icon."""
        if len(item.lines) != 1:
            return
        ln = item.lines[0]
        for o in self._tracks:
            if o is t:
                continue
            bx0, by0, bx1, by1 = o.cand.box
            if min(by1, ln.y1) - max(by0, ln.y0) < 0.5 * (ln.y1 - ln.y0):
                continue
            if bx0 >= ln.x1:  # a neighbour on the right
                edge = bx0 + int(0.3 * o.cand.cap)
                item.icon_r = edge if item.icon_r is None else min(item.icon_r, edge)
            elif bx1 <= ln.x0:  # on the left
                edge = bx1 - int(0.3 * o.cand.cap)
                item.icon_l = edge if item.icon_l is None else max(item.icon_l, edge)

    def _arabic(self, text: str, head: bool = False, known_only: bool = False, engine: bool = True):
        """The Arabic of a screen text, None to leave it as it is, or _LATER when only the engine
        can tell and `engine` is False."""
        key = f"{'H' if head else ''}{'K' if known_only else ''}{text}"
        if key in self._memo:
            return self._memo[key]
        ar: str | None
        game = self.game
        if head:  # a sender's name: from the game's list only, else it stays as it is
            low = text.lower()
            ar = next((a for e, a in self.translator.glossary.items() if e.lower() == low), None)
        elif known_only:  # the busy middle of the screen: the game's own screen words only
            ar = game.ui_word(game.fix_reading(text)) if game is not None else None
        else:
            word = game.ui_word(game.fix_reading(text)) if game is not None else None
            single = len(text.split()) == 1
            name = self._name_for(text) if single else None
            if word is not None:
                ar = word
            elif name is not None:
                ar = name
            elif single and (text[:1].islower() or len(text.strip(".,!?:")) <= 3
                             or (text.isupper() and len(text.strip(".,!?:")) <= 5)):
                # A piece of a word ("pdate", "ALK"), or a short label the table does not know
                # (a car's brand): drawn wrong it would break the screen, left alone it does not.
                ar = None
            elif game is not None and game.keep_english(game.fix_reading(text)):
                ar = None
            elif not engine:
                return _LATER
            else:
                deadline = time.monotonic() + ENGINE_WAIT_MS / 1000.0
                while self.busy() and time.monotonic() < deadline:
                    time.sleep(0.01)  # the subtitles first
                try:
                    ar = self.translator.translate(text)[0]
                except Exception:
                    ar = None
        self._memo[key] = ar
        return ar

    def _name_for(self, word: str) -> str | None:
        """A name from the game's list for a one-word item, also when its end was cut off
        ("SHIRLE" for Shirley, the last letter under a button)."""
        w = word.strip(".,!?:").lower()
        if len(w) < 3:
            return None
        for en, ar in self.translator.glossary.items():
            e = en.lower()
            if e == w or (len(w) >= 4 and " " not in e and e.startswith(w) and len(e) - len(w) <= 2):
                return ar
        return None

    # -- drawing and sending ------------------------------------------------------------------

    def _redraw_moving(self, frame: np.ndarray, now: float) -> bool:
        """Covers over the moving scene are redone from the newest picture now and then."""
        if now - self._last_refresh < REFRESH_MS:
            return False
        self._last_refresh = now
        changed = False
        for t in self._tracks:
            if t.state == "shown" and not t.flat and t.item is not None \
                    and not still_around(self._refresh_frame, frame, t.item):
                t.state, t.patches = "read", []  # the scene moved: back to English, tried again
                t.version += 1
                changed = True
        self._refresh_frame = frame
        return changed

    def _send(self, _refreshed: bool, now: float = 0.0) -> None:
        self._choose_window()
        shown = [t for t in self._tracks if t.state == "shown" and t.patches]
        groups = pack_layers(shown, self.slots)
        # What a layer holds: its texts and how often each was redrawn. Only changes are sent.
        want = {gid: tuple(sorted((id(t), t.arabic, t.version) for t in ts)) for gid, ts in groups.items()}
        with self._lock:
            before = dict(self._sent)
        stale = [gid for gid in before if gid not in groups]
        changed = [gid for gid in groups if before.get(gid) != want[gid]]
        # A menu shows up whole: while words of its part of the screen still wait to be read
        # (a few hundred ms at most), what changed there is held back.
        waiting = {t.cand.zone for t in self._tracks if t.state == "wait" and t.seen >= SETTLE_SEARCHES}
        held = set(waiting)
        if held:
            # Only a layer that is not up yet waits, and never longer than HOLD_WHOLE_MS after its
            # first text was read: over a moving scene new letter-like rows keep coming.
            keep_back = [gid for gid in changed if gid not in before
                         and any(t.cand.zone in held for t in groups[gid])
                         and now - min(t.shown_at for t in groups[gid]) < HOLD_WHOLE_MS]
            for gid in keep_back:
                changed.remove(gid)
                want[gid] = before.get(gid, ())  # sent later, once the rest is read
            stale = [gid for gid in stale if gid not in keep_back]
        if stale:
            self.link.clear(stale)
        if changed:
            layers = []
            for gid in changed:
                layer = compose([p for t in groups[gid] for p in t.patches], gid)
                if layer is not None:
                    layers.append(self._to_overlay(layer))
            for k in range(0, len(layers), P.MAX_LAYERS):
                self.link.show(self.window, layers[k:k + P.MAX_LAYERS])
            self._last_keep = now_ms()
        with self._lock:
            self._sent = {gid: want[gid] for gid in groups if gid in before or gid in changed}

    def _to_overlay(self, layer: render.RgbaLayer) -> P.Layer:
        """Frame pixels to the TV's overlay pixels (the same size on this setup), then PNG."""
        caps = getattr(self.link, "caps", {}) or {}
        ow, oh = caps.get("w", 1920), caps.get("h", 1080)
        fh, fw = self._shape
        bgra, x, y = layer.bgra, layer.x, layer.y
        if (fw, fh) != (ow, oh):
            sx, sy = ow / fw, oh / fh
            x0, y0 = int(round(x * sx)), int(round(y * sy))
            x1, y1 = int(round((x + layer.w) * sx)), int(round((y + layer.h) * sy))
            bgra = cv2.resize(bgra, (max(1, x1 - x0), max(1, y1 - y0)), interpolation=cv2.INTER_AREA)
            x, y = x0, y0
        bgra = np.ascontiguousarray(bgra[:P.MAX_LAYER_H, :P.MAX_LAYER_W])
        ok, buf = cv2.imencode(".png", bgra, [cv2.IMWRITE_PNG_COMPRESSION, 1])
        if not ok:
            raise RuntimeError("PNG encoding failed")
        return P.Layer(id=layer.id, png=buf.tobytes(), x=int(x), y=int(y), w=bgra.shape[1], h=bgra.shape[0],
                       z=3, ttl_ms=LAYER_TTL_MS)

    def _clear_all(self) -> None:
        with self._lock:
            ids = list(self._sent)
            self._sent.clear()
            self._tracks = []
        if ids:
            try:
                self.link.clear(ids)
            except TvLinkError:
                pass
