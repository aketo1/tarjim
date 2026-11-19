"""Find screen text: menu items, button prompts, notices and phone messages.

The subtitle detector (detect.py) looks for one block of light text at the bottom of the
picture. A game's own screens are different: many short items at once (a menu down the
left, prompts stacked at the right, a phone message on a white card), each to be translated
on its own and drawn back in its own place. This module only finds them; screen_text.py
reads, translates and draws them.

Two kinds of text are found:
  - light strokes: white letters on a dark panel or over the scene;
  - dark strokes on a light, even ground: a phone message, the selected row of a menu.

Rows are looked for at half the picture's size (several times faster, and letters 16 px tall
at 1080p are still 8 px there); each item found is then cut out of the full picture, where
its exact strokes are taken for the cover and the reader. Sizes scale with the frame height.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .detect import Block, Line


@dataclass(frozen=True)
class Zone:
    """Part of the screen where a game puts its own text, as fractions of the frame."""

    name: str
    x0: float
    y0: float
    x1: float
    y1: float
    align: str  # "left": items grow to the right (icons on their left); "right": the other way
    cards: bool = False  # look for paragraphs of dark text on a light ground (phone messages)
    dark: bool = True  # also look for dark rows on a light ground (a selected menu item)
    items: bool = True  # look for rows of light text (False: messages only)
    known_only: bool = False  # draw only words the game's table knows (a busy part of the screen)

    def box(self, fw: int, fh: int) -> tuple[int, int, int, int]:
        return int(self.x0 * fw), int(self.y0 * fh), int(round(self.x1 * fw)), int(round(self.y1 * fh))


@dataclass
class Item:
    """One piece of screen text: a menu row, a prompt, a notice, or a message's paragraph."""

    zone: str
    x0: int
    y0: int
    x1: int
    y1: int
    mask: np.ndarray  # uint8 0/255 strokes, shape (y1-y0, x1-x0)
    lines: list[Line]  # frame coordinates; one per text row
    dark: bool  # dark letters on a light ground
    cap: int  # height of the tall letters, px
    align: str
    panel_bgr: tuple[int, int, int] | None = None  # an even ground's colour: the cover is drawn flat
    head: bool = False  # a message's first row (the sender's name): names only
    hard_x0: int | None = None  # nothing left of this is covered (a menu's icon column)
    icon_l: int | None = None  # the Arabic stays right of this (an icon before the English)
    icon_r: int | None = None  # ... and left of this (a button after it)

    @property
    def w(self) -> int:
        return self.x1 - self.x0

    @property
    def h(self) -> int:
        return self.y1 - self.y0

    def block(self) -> Block:
        """The item as a Block, for the reader and the fill of the subtitle code."""
        return Block(self.x0, self.y0, self.x1, self.y1, self.mask, list(self.lines))


@dataclass(frozen=True)
class FindParams:
    tophat_kernel: int = 15
    tophat_min: int = 45
    bright_min: int = 150  # light text: its darkest channel is at least this
    dark_max: int = 150  # dark text: its brightest channel is at most this
    glyph_h_min: int = 9
    glyph_h_max: int = 48
    icon_ratio: float = 1.35  # taller than this times the row's letters: an icon or a button
    # A gap wider than this times the letter height starts a new item. Wide enough for a word
    # whose first letter was lost to the scene ("Map  pdated"); items side by side are always
    # set apart by an icon or a button, which splits them anyway.
    item_gap: float = 1.3
    para_gap: float = 1.6  # the same inside a message (its words are never that far apart)
    min_glyphs: int = 2
    ground_min: int = 175  # dark letters count only on a ground at least this light ...
    ground_flat: float = 22.0  # ... and this even
    card_min: int = 220  # a message's ground is lighter still


SCALE = 0.5  # rows are looked for at this fraction of the picture's size
MAX_GLYPHS = 900  # a zone with more letter-sized blobs is a busy scene: only the first rows count


def _odd(v: float) -> int:
    n = max(3, int(round(v)))
    return n if n % 2 else n + 1


def strokes(crop_bgr: np.ndarray, dark: bool, p: FindParams, s: float) -> np.ndarray:
    """Thin strokes much lighter (or darker) than their surroundings (uint8 0/255)."""
    b, g, r = crop_bgr[:, :, 0], crop_bgr[:, :, 1], crop_bgr[:, :, 2]
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (_odd(p.tophat_kernel * s),) * 2)
    if dark:
        m = cv2.max(cv2.max(b, g), r)
        hat = cv2.morphologyEx(m, cv2.MORPH_BLACKHAT, k)
        return ((hat > p.tophat_min) & (m < p.dark_max)).astype(np.uint8) * 255
    m = cv2.min(cv2.min(b, g), r)
    hat = cv2.morphologyEx(m, cv2.MORPH_TOPHAT, k)
    return ((hat > p.tophat_min) & (m > p.bright_min)).astype(np.uint8) * 255


@dataclass
class _Glyph:
    x: int
    y: int
    w: int
    h: int

    @property
    def cy(self) -> float:
        return self.y + self.h / 2.0


@dataclass
class _Row:
    glyphs: list[_Glyph] = field(default_factory=list)
    y0: int = 0
    y1: int = 0

    def add(self, g: _Glyph) -> None:
        if not self.glyphs:
            self.y0, self.y1 = g.y, g.y + g.h
        else:
            self.y0, self.y1 = min(self.y0, g.y), max(self.y1, g.y + g.h)
        self.glyphs.append(g)


@dataclass
class _Run:
    """A run of letters at the search scale, then in full-picture pixels of its zone crop."""

    x0: int
    y0: int
    x1: int
    y1: int
    cap: int
    n: int
    icon_l: int | None = None  # right edge of an icon right before it
    icon_r: int | None = None  # left edge of an icon (a button) right after it
    tall: float = 0.0  # share of its letters as tall as capitals (about 1 for a line in capitals)


def _pct(values: list[int], q: float) -> float:
    """A percentile of a short list (numpy's costs more than the whole row for a few values)."""
    v = sorted(values)
    return float(v[min(len(v) - 1, int(q * (len(v) - 1) + 0.5))])


def _glyphs(mask: np.ndarray, p: FindParams, s: float) -> list[_Glyph]:
    _n, _labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    st = stats[1:]
    if not len(st):
        return []
    h_min, h_max = max(3.0, p.glyph_h_min * s), p.glyph_h_max * s
    w, h, area = st[:, 2], st[:, 3], st[:, 4]
    ok = (h >= h_min) & (h <= h_max) & (w <= 4.0 * h_max) & (area >= max(3.0, 8 * s * s))
    # strokes, not blotches: a letter fills well under its whole box (an l or an I is a thin bar)
    ok &= (area <= 0.85 * w * h) | (w <= 0.4 * h)
    idx = np.nonzero(ok)[0][:MAX_GLYPHS]
    return [_Glyph(int(st[i, 0]), int(st[i, 1]), int(st[i, 2]), int(st[i, 3])) for i in idx]


def _rows(glyphs: list[_Glyph]) -> list[_Row]:
    """Glyphs whose vertical middles line up, by the order of their middles."""
    rows: list[_Row] = []
    for g in sorted(glyphs, key=lambda g: g.cy):
        # Sorted by middle: only the last few rows can still take this glyph.
        for row in reversed(rows[-4:]):
            mid = (row.y0 + row.y1) / 2.0
            if abs(g.cy - mid) <= 0.45 * max(g.h, row.y1 - row.y0):
                row.add(g)
                break
        else:
            row = _Row()
            row.add(g)
            rows.append(row)
    return rows


def _letters_like(gs: list[_Glyph], cap: float) -> bool:
    """Letters stand on one line and have like heights; leaves, fences and wires do not."""
    if len(gs) < 3:
        return True  # judged by the reader (a two-letter word is too short to tell)
    bottoms = [g.y + g.h for g in gs]
    base = _pct(bottoms, 0.5)
    on_line = sum(1 for b in bottoms if abs(b - base) <= 0.22 * cap + 1)
    like = sum(1 for g in gs if 0.40 * cap <= g.h <= 1.15 * cap + 1)
    return on_line >= 0.6 * len(gs) and like >= 0.8 * len(gs)


def _split(row: _Row, p: FindParams, align: str, gap: float, icon_gap: float = 0.75) -> list[tuple[list[_Glyph], int]]:
    """Split a row into items at wide gaps; leave out icons. Returns (glyphs, letter height)."""
    # A button is a ring with its symbol inside: the symbol is part of the ring, not a letter.
    inside = {id(a) for a in row.glyphs for b in row.glyphs
              if a is not b and b.x <= a.x and a.x + a.w <= b.x + b.w and b.y <= a.y and a.y + a.h <= b.y + b.h
              and b.w * b.h > a.w * a.h}
    if inside:
        row = _Row([g for g in row.glyphs if id(g) not in inside], row.y0, row.y1)
    # measured on the tall letters: in "Quit Mission" most letters are small, and the Q (with its
    # tail) would otherwise look like an icon
    cap0 = _pct([g.h for g in row.glyphs], 0.85)
    letters = [g for g in row.glyphs if g.h <= 1.45 * cap0]
    if len(letters) < p.min_glyphs:
        return []
    # The tall letters' height: the tallest of those that stand on the line (a p or a g hangs
    # below it). "Game" has one capital among small letters; its size is the capital's.
    base = _pct([g.y + g.h for g in letters], 0.5)
    mid_h = _pct([g.h for g in letters], 0.5)
    standing = [g.h for g in letters if abs(g.y + g.h - base) <= 0.2 * mid_h + 1]
    cap = max(2, int(max(standing) if standing else _pct([g.h for g in letters], 0.85)))
    # A button between two prompts ("PHOTO STUDIO ⊡ SELECT"): a square shape larger than the
    # letters, standing apart on both sides. (A capital is as big but touches its word: "Quit".)
    xs = sorted(letters, key=lambda g: g.x)
    med_w = _pct([g.w for g in xs], 0.5)
    buttons = set()
    for k, g in enumerate(xs):
        if not (0.75 <= g.w / max(1, g.h) <= 1.35 and g.h >= 1.25 * mid_h and g.w >= 1.8 * med_w):
            continue
        left_gap = g.x - (xs[k - 1].x + xs[k - 1].w) if k > 0 else cap
        right_gap = xs[k + 1].x - (g.x + g.w) if k + 1 < len(xs) else cap
        if left_gap >= 0.4 * cap and right_gap >= 0.4 * cap:
            buttons.add(id(g))
    letters = [g for g in letters if id(g) not in buttons]
    if len(letters) < p.min_glyphs:
        return []
    icons = sorted((g for g in row.glyphs if g.h > p.icon_ratio * cap or id(g) in buttons), key=lambda g: g.x)
    out: list[list[_Glyph]] = []
    cur: list[_Glyph] = []
    right = 0
    for g in sorted(letters, key=lambda g: g.x):
        # An icon between two letters always ends the item, however close it sits.
        if cur and (g.x - right > gap * cap or any(right <= i.x + i.w / 2 <= g.x for i in icons)):
            out.append(cur)
            cur = []
        right = g.x + g.w if not cur else max(right, g.x + g.w)
        cur.append(g)
    if cur:
        out.append(cur)
    # A menu's icon sits a little apart before the word (after it, for a button prompt):
    # a short first (last) piece set off by half a letter's height is that icon.
    if align in ("left", "right"):
        trimmed = []
        for gs in out:
            order = gs if align == "left" else gs[::-1]
            for k in range(1, min(5, len(order) - 1)):
                a, b = order[k - 1], order[k]
                gap_px = (b.x - (a.x + a.w)) if align == "left" else (a.x - (b.x + b.w))
                head = order[:k]
                head_w = max(g.x + g.w for g in head) - min(g.x for g in head)
                if gap_px >= icon_gap * cap and head_w <= 1.8 * cap:
                    order = order[k:]
                    break
            trimmed.append(order if align == "left" else order[::-1])
        out = trimmed
    # A button drawn right after a prompt (or a symbol right before a notice) is about as tall as
    # the capitals and so is not taken for an icon above; it is a lone, nearly square shape a bit
    # taller than the letters beside it, a little apart from them.
    final: list[tuple[list[_Glyph], int]] = []
    for gs in out:
        gs = sorted(gs, key=lambda g: g.x)
        for end in (-1, 0):
            if len(gs) < 3:
                break
            g = gs[end]
            rest = gs[:-1] if end == -1 else gs[1:]
            nb = rest[-1] if end == -1 else rest[0]
            med = _pct([q.h for q in rest], 0.5)
            med_w = _pct([q.w for q in rest], 0.5)
            gap_px = (g.x - (nb.x + nb.w)) if end == -1 else (nb.x - (g.x + g.w))
            # (the capital of "Game" is square-ish and taller too, but it touches its word; a
            # button, blurred onto the last letter at the search's size, is much wider as well)
            # at the start, only a shape taller than every letter after it: a word's capital
            # (the Q of "Quit", with its tail) is not
            tallest = max(q.h for q in rest)
            apart = (0.75 <= g.w / max(1, g.h) <= 1.35 and g.h >= 1.08 * med and gap_px >= 0.45 * med
                     and (end == -1 or g.h >= 1.15 * tallest))
            # by size only at the end: buttons come after their word; a word's first letter
            # (the G of "Game") can be as big
            big = end == -1 and g.h >= 1.2 * med and g.w >= 2.0 * med_w
            if apart or big:
                gs = rest
                # a piece of the same button stuck to it (its outline, its label)
                nb = gs[-1] if end == -1 else gs[0]
                touching = (nb.x + nb.w >= g.x - 1) if end == -1 else (g.x + g.w >= nb.x - 1)
                if len(gs) > 2 and touching and nb.h < 0.8 * med:
                    gs = gs[:-1] if end == -1 else gs[1:]
        c = max(2, int(max((q.h for q in gs if abs(q.y + q.h - base) <= 0.2 * mid_h + 1), default=cap)))
        final.append((gs, c))
    return [(gs, c) for gs, c in final
            if len(gs) >= p.min_glyphs and (max(g.x + g.w for g in gs) - min(g.x for g in gs)) >= 1.1 * c
            and _letters_like(gs, c)]


def _icon_sides(row: _Row, gs: list[_Glyph], cap: int, p: FindParams) -> tuple[int | None, int | None]:
    """The inner edges of the icons right beside an item (its button, its symbol), if any:
    (right edge of an icon on its left, left edge of an icon on its right)."""
    x0, x1 = min(g.x for g in gs), max(g.x + g.w for g in gs)
    left = right = None
    ids = {id(g) for g in gs}
    for g in row.glyphs:
        if id(g) in ids:
            continue
        iconish = g.h > p.icon_ratio * cap or (g.h >= 0.9 * cap and g.w >= 0.9 * cap)
        if not iconish:
            continue
        if 0 <= x0 - (g.x + g.w) <= 1.6 * cap:
            left = g.x + g.w if left is None else max(left, g.x + g.w)
        if 0 <= g.x - x1 <= 1.6 * cap:
            right = g.x if right is None else min(right, g.x)
    return left, right


def _ground(crop_bgr: np.ndarray, mask: np.ndarray) -> tuple[float, float, tuple[int, int, int]]:
    """Brightness, evenness and colour of the pixels around the strokes."""
    grown = cv2.dilate(mask, np.ones((3, 3), np.uint8))
    around = crop_bgr[grown == 0]
    if len(around) < 8:
        return 0.0, 255.0, (0, 0, 0)
    if len(around) > 400:
        around = around[:: len(around) // 400]
    m = around.max(axis=1).astype(np.float32)
    bgr = np.median(around, axis=0)
    return float(np.median(m)), float(m.std()), (int(bgr[0]), int(bgr[1]), int(bgr[2]))


Ground = tuple[float, float, tuple[int, int, int]]


def _runs(crop: np.ndarray, dark: bool, p: FindParams, s: float, align: str, gap: float,
          blank: list[tuple[int, int, int, int]], icon_gap: float = 0.75) -> list[list[tuple[_Run, Ground | None]]]:
    """Rows of letters in a zone crop, found at the search scale. Coordinates: full crop pixels.
    For dark letters, the ground around each run is measured too (at the search scale)."""
    small = cv2.resize(crop, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)
    ss = s * SCALE
    mask = strokes(small, dark, p, ss)
    for x0, y0, x1, y1 in blank:
        mask[max(0, int(y0 * SCALE)):max(0, int(y1 * SCALE) + 1), max(0, int(x0 * SCALE)):max(0, int(x1 * SCALE) + 1)] = 0
    glyphs = _glyphs(mask, p, ss)
    if len(glyphs) < p.min_glyphs:
        return []
    k = 1.0 / SCALE
    out: list[list[tuple[_Run, Ground | None]]] = []
    for row in sorted(_rows(glyphs), key=lambda r: r.y0):
        runs = []
        for gs, cap in _split(row, p, align, gap, icon_gap):
            x0, y0 = min(g.x for g in gs), min(g.y for g in gs)
            x1, y1 = max(g.x + g.w for g in gs), max(g.y + g.h for g in gs)
            ground = None
            if dark:
                pad = max(2, int(0.4 * cap))
                ground = _ground(small[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad],
                                 mask[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad])
            il, ir = _icon_sides(row, gs, cap, p)
            tall = sum(1 for g in gs if g.h >= 0.85 * cap) / len(gs)
            runs.append((_Run(int(x0 * k), int(y0 * k), int(np.ceil(x1 * k)), int(np.ceil(y1 * k)),
                              int(round(cap * k)), len(gs),
                              None if il is None else int(il * k), None if ir is None else int(ir * k), tall), ground))
        if runs:
            out.append(runs)
    return out


@dataclass
class Cand:
    """Screen text found by the search, before its exact strokes are taken (frame pixels)."""

    zone: str
    runs: list[_Run]  # one per text row
    dark: bool
    align: str
    panel_bgr: tuple[int, int, int] | None = None
    head: bool = False
    hard_x0: int | None = None  # nothing left of this is the item's (a menu's icon column)

    @property
    def cap(self) -> int:
        return int(round(float(np.median([r.cap for r in self.runs]))))

    @property
    def box(self) -> tuple[int, int, int, int]:
        cap = self.cap
        px, py = max(4, int(0.40 * cap)), max(3, int(0.45 * cap))
        return (min(r.x0 for r in self.runs) - px, min(r.y0 for r in self.runs) - py,
                max(r.x1 for r in self.runs) + px, max(r.y1 for r in self.runs) + py)


def _shift(run: _Run, ox: int, oy: int) -> _Run:
    return _Run(run.x0 + ox, run.y0 + oy, run.x1 + ox, run.y1 + oy, run.cap, run.n,
                None if run.icon_l is None else run.icon_l + ox, None if run.icon_r is None else run.icon_r + ox,
                run.tall)


def _align_by_icons(run: _Run, default: str) -> str:
    """The Arabic grows away from the item's icons: after an icon on its left it starts there;
    before a button on its right it ends there; between the two it is centred."""
    if run.icon_l is not None and run.icon_r is not None:
        return "center"
    if run.icon_l is not None:
        return "left"
    if run.icon_r is not None:
        return "right"
    return default


def build_item(frame: np.ndarray, cand: Cand, p: FindParams | None = None) -> Item | None:
    """Cut a found text out of the full picture: its box with a margin and its exact strokes."""
    p = p or FindParams()
    s = frame.shape[0] / 1080.0
    runs = cand.runs
    cap = cand.cap
    x0, y0 = min(r.x0 for r in runs), min(r.y0 for r in runs)
    x1, y1 = max(r.x1 for r in runs), max(r.y1 for r in runs)
    bx0, by0, bx1, by1 = cand.box
    # The search's box is a few pixels off at full size (a first letter can stick out of it):
    # look a little wider, and keep the letters whose middle lies in the item, at its height,
    # not cut by the edge of what was looked at (the scene around, a neighbour's icon).
    wide = int(0.8 * cap)
    bx0, by0 = max(0, bx0 - wide), max(0, by0)
    bx1, by1 = min(frame.shape[1], bx1 + wide), min(frame.shape[0], by1)
    if bx1 - bx0 < 4 or by1 - by0 < 4:
        return None
    patch = np.ascontiguousarray(frame[by0:by1, bx0:bx1])
    raw = strokes(patch, cand.dark, p, s)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(raw, connectivity=8)
    keep = np.zeros(n, dtype=bool)
    pw, ph = bx1 - bx0, by1 - by0
    left_slack = 0.5 * cap if cand.hard_x0 is None else 0.0
    band = [(r.y0 - by0 - int(0.45 * cap), r.y1 - by0 + int(0.45 * cap), r.x0 - bx0 - left_slack, r.x1 - bx0 + 0.5 * cap)
            for r in runs]
    if cand.hard_x0 is not None:  # an icon's part must not be kept even if its middle is close
        band = [(b0, b1, max(l0, cand.hard_x0 - bx0), l1) for b0, b1, l0, l1 in band]
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[i])
        if x <= 0 or x + w >= pw or y < 0 or y + h > ph or h > 1.35 * cap or area < 2:
            continue
        cx = x + w / 2.0
        if any(b0 <= y and y + h <= b1 and l0 <= cx <= l1 for b0, b1, l0, l1 in band):
            keep[i] = True
    mask = keep[labels].astype(np.uint8) * 255
    if not mask.any():
        return None
    # Each line's ends from the letters themselves, not from the search.
    lines = []
    for r in runs:
        rows = mask[max(0, r.y0 - by0):max(0, r.y1 - by0)]
        cols = np.nonzero(rows.max(axis=0))[0] if rows.size else np.array([], dtype=int)
        lx0, lx1 = (int(cols[0]) + bx0, int(cols[-1]) + 1 + bx0) if len(cols) else (r.x0, r.x1)
        lines.append(Line(lx0, r.y0, lx1, r.y1, r.n))
    return Item(cand.zone, bx0, by0, bx1, by1, mask, lines, cand.dark, cap, cand.align,
                panel_bgr=cand.panel_bgr, head=cand.head, hard_x0=cand.hard_x0,
                icon_l=runs[0].icon_l if len(runs) == 1 else None, icon_r=runs[0].icon_r if len(runs) == 1 else None)


def find_items(frame: np.ndarray, zone: Zone, p: FindParams | None = None,
               skip: list[tuple[int, int, int, int]] | None = None) -> list[Cand]:
    """Every row of light text in the zone (and of dark text on light rows), split into items."""
    p = p or FindParams()
    fh, fw = frame.shape[:2]
    s = fh / 1080.0
    zx0, zy0, zx1, zy1 = zone.box(fw, fh)
    crop = frame[zy0:zy1, zx0:zx1]
    blank = [(x0 - zx0, y0 - zy0, x1 - zx0, y1 - zy0) for x0, y0, x1, y1 in (skip or [])]
    out: list[Cand] = []
    for dark in ((True, False) if zone.dark else (False,)):
        if not dark:
            # On a light row with dark letters, the light gaps between the letters look like
            # light strokes: that row was read as dark text already.
            for c in out:
                bx0, by0, bx1, by1 = c.box
                blank.append((bx0 - zx0, by0 - zy0, bx1 - zx0, by1 - zy0))
        cw, ch = crop.shape[1], crop.shape[0]
        for row in _runs(crop, dark, p, s, zone.align, p.item_gap, blank):
            for run, ground in row:
                # A line the zone's edge cuts ("ICK UP GROCERIES") is left alone: half a word
                # translated would break the screen. The picture's own edge cuts nothing.
                if (run.x0 <= 3 and zx0 > 0) or (run.x1 >= cw - 3 and zx1 < fw) \
                        or (run.y0 <= 2 and zy0 > 0) or (run.y1 >= ch - 2 and zy1 < fh):
                    continue
                if any(min(run.y1, b1) - max(run.y0, b0) > 0 and (abs(run.x0 - a1) <= 4 or abs(run.x1 - a0) <= 4)
                       for a0, b0, a1, b1 in blank[:len(skip or [])]):
                    continue  # cut by a place that is not searched (the subtitles')
                if ground is not None:
                    # Dark letters count only on a light, even ground (a selected row, a panel),
                    # never on the scene: fences, wires and shadows make letter-like rows too.
                    level, spread, _bgr = ground
                    if level < p.ground_min or spread > p.ground_flat:
                        continue
                run = _shift(run, zx0, zy0)
                align = zone.align if zone.align == "left" else _align_by_icons(run, zone.align)
                out.append(Cand(zone.name, [run], dark, align))
    out = _same_line(out)
    if zone.align == "left":
        _icon_column(out)
    if not zone.known_only:  # a hint box's lines are one text, at the left or the right
        out = _paragraphs(out)
    return out


def _same_line(cands: list[Cand]) -> list[Cand]:
    """Words of one line set wide apart (film credits: "A  NAME  PRODUCTION") are one text, unless
    an icon or a button stands between them (a button bar): half a line translated would break it."""
    out: list[Cand] = []
    for c in sorted(cands, key=lambda c: c.runs[0].x0):  # left to right; the line is found below
        if len(c.runs) != 1:
            out.append(c)
            continue
        b = c.runs[0]
        best, best_gap = None, None
        for prev in out:
            if len(prev.runs) != 1 or prev.dark != c.dark:
                continue
            a = prev.runs[0]
            cap = max(a.cap, b.cap)
            overlap = min(a.y1, b.y1) - max(a.y0, b.y0)
            gap = b.x0 - a.x1
            icon_between = a.icon_r is not None or b.icon_l is not None
            # In a sentence (small letters) a short word the search missed ("the") leaves a
            # wider hole than between the capitals of a credit line.
            reach = 4.0 if a.tall < 0.7 and b.tall < 0.7 else 2.6
            if (overlap >= 0.6 * min(a.y1 - a.y0, b.y1 - b.y0) and 0 <= gap <= reach * cap
                    and abs(a.cap - b.cap) <= 0.25 * cap and not icon_between
                    and (best_gap is None or gap < best_gap)):
                best, best_gap = prev, gap
        if best is None:
            out.append(c)
            continue
        a = best.runs[0]
        best.runs[0] = _Run(a.x0, min(a.y0, b.y0), b.x1, max(a.y1, b.y1), max(a.cap, b.cap), a.n + b.n,
                            a.icon_l, b.icon_r, (a.tall * a.n + b.tall * b.n) / (a.n + b.n))
        if b.icon_r is not None:
            best.align = c.align
    return out


def _paragraphs(cands: list[Cand]) -> list[Cand]:
    """Lines of one heading or one sentence under each other (close, starting at the same place,
    written the same way: capitals or not) are one text, read and translated together. Menu
    rows stand much further apart, and a heading over its subtitle differs in its capitals."""
    out: list[Cand] = []
    for c in sorted(cands, key=lambda c: (c.runs[0].y0, c.runs[0].x0)):
        prev = out[-1] if out else None
        if prev is not None and prev.dark == c.dark and len(c.runs) == 1:
            a, b = prev.runs[-1], c.runs[0]
            cap = max(a.cap, b.cap)
            same_style = abs(a.tall - b.tall) <= 0.3
            if (abs(a.x0 - b.x0) <= 0.6 * cap and 0 <= b.y0 - a.y1 <= 0.75 * cap
                    and abs(a.cap - b.cap) <= 0.25 * cap and same_style):
                prev.runs.append(b)
                continue
        out.append(c)
    return out


def _icon_column(cands: list[Cand]) -> None:
    """In a menu, the words of every row start at the same place, right of a column of icons.
    A row that seems to start a little further left took a piece of its icon with it: it is
    cut back to where the others start, and nothing left of that is ever covered."""
    if len(cands) < 3:
        return
    starts = sorted(c.runs[0].x0 for c in cands if len(c.runs) == 1)
    best, col = 0, None
    for s in starts:  # the start most rows share
        n = sum(1 for t in starts if abs(t - s) <= 4)
        if n > best:
            best, col = n, s
    if col is None or best < 3:
        return
    for c in cands:
        if len(c.runs) != 1:
            continue
        r, cap = c.runs[0], c.cap
        if abs(r.x0 - col) <= 4 or col - 1.8 * cap <= r.x0 < col - 4:
            if r.x0 < col - 4:
                c.runs[0] = _Run(col - 2, r.y0, r.x1, r.y1, r.cap, r.n)
            c.hard_x0 = col - 3


def _on_card(crop: np.ndarray, run: _Run, p: FindParams, s: float):
    """The longest stretch of a line, from either end inward, whose ground is a card's."""
    step = max(4, int(1.5 * run.cap))
    pad = max(2, int(0.4 * run.cap))
    ok = []
    for x in range(run.x0, run.x1, step):
        c = np.ascontiguousarray(crop[max(0, run.y0 - pad):run.y1 + pad, max(0, x - pad):min(crop.shape[1], x + step + pad)])
        if c.size == 0:
            ok.append((x, False, None))
            continue
        level, spread, bgr = _ground(c, strokes(c, True, p, s))
        ok.append((x, level >= p.card_min and spread <= p.ground_flat, bgr))
    best, cur = [], []
    for x, good, bgr in ok:
        cur = cur + [(x, bgr)] if good else []
        if len(cur) > len(best):
            best = list(cur)
    if not best or len(best) * step < 3 * run.cap:
        return None
    x0, x1 = max(run.x0, best[0][0]), min(run.x1, best[-1][0] + step)
    return _Run(x0, run.y0, x1, run.y1, run.cap, run.n), best[len(best) // 2][1]


def find_cards(frame: np.ndarray, zone: Zone, p: FindParams | None = None) -> list[Cand]:
    """Phone messages: paragraphs of dark text on a light, even ground. One item per paragraph.

    The card itself is not looked for: on sand or a wall in the sun, blown out to plain white,
    its edge cannot be seen. Its text can: dark pieces of rows on a ground that is light and
    even right around the letters, close to each other. Pieces close together are one message;
    in it, pieces at the same height are one line, and a line set apart above the rest is the
    sender's name."""
    p = p or FindParams()
    fh, fw = frame.shape[:2]
    s = fh / 1080.0
    zx0, zy0, zx1, zy1 = zone.box(fw, fh)
    crop = frame[zy0:zy1, zx0:zx1]
    pieces: list[tuple[_Run, tuple[int, int, int]]] = []
    for row in _runs(crop, True, p, s, "", p.para_gap, []):
        for run, g in row:
            if g is not None and g[0] >= p.card_min and g[1] <= p.ground_flat:
                pieces.append((run, g[2]))
            elif g is not None and g[0] >= p.card_min:
                # The line ran past the card's edge (a darker scene beside it): keep the part
                # of it that lies on the card.
                kept = _on_card(crop, run, p, s)
                if kept is not None:
                    pieces.append(kept)
    if not pieces:
        return []
    # Messages: pieces whose boxes, grown by a little, touch (union-find).
    parent = list(range(len(pieces)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, (a, _ga) in enumerate(pieces):
        for j in range(i + 1, len(pieces)):
            b = pieces[j][0]
            c = max(a.cap, b.cap)
            # (the sender's name sits about two letters above the message: still one card)
            if (a.x0 - 2.5 * c <= b.x1 and b.x0 <= a.x1 + 2.5 * c
                    and a.y0 - 2.6 * c <= b.y1 and b.y0 <= a.y1 + 2.6 * c):
                parent[root(i)] = root(j)
    groups: dict[int, list[tuple[_Run, tuple[int, int, int]]]] = {}
    for i, pc in enumerate(pieces):
        groups.setdefault(root(i), []).append(pc)
    cands: list[Cand] = []
    for group in groups.values():
        # Lines: pieces at the same height, left to right.
        lines: list[list[tuple[_Run, tuple[int, int, int]]]] = []
        for pc in sorted(group, key=lambda t: (t[0].y0 + t[0].y1) / 2):
            r = pc[0]
            if lines:
                last = lines[-1]
                ly0, ly1 = min(q[0].y0 for q in last), max(q[0].y1 for q in last)
                if min(ly1, r.y1) - max(ly0, r.y0) >= 0.4 * min(ly1 - ly0, r.y1 - r.y0):
                    last.append(pc)
                    continue
            lines.append([pc])
        runs: list[_Run] = []
        bgrs: list[tuple[int, int, int]] = []
        for line in lines:
            line.sort(key=lambda t: t[0].x0)
            # The avatar before the sender's name: a short piece set well apart from the rest.
            if len(line) > 1:
                first, second = line[0][0], line[1][0]
                if first.x1 - first.x0 <= 2.2 * second.cap and second.x0 - first.x1 >= 1.2 * second.cap:
                    line = line[1:]
            rs = [q[0] for q in line]
            runs.append(_Run(min(r.x0 for r in rs), min(r.y0 for r in rs), max(r.x1 for r in rs),
                             max(r.y1 for r in rs), max(r.cap for r in rs), sum(r.n for r in rs)))
            bgrs.extend(q[1] for q in line)
        med = np.median(np.array(bgrs, dtype=np.float32), axis=0)
        bgr = (int(med[0]), int(med[1]), int(med[2]))
        # Paragraphs: the lines split where the gap between two is wider than a line's.
        paras: list[list[_Run]] = [[runs[0]]]
        for r in runs[1:]:
            prev = paras[-1][-1]
            if r.y0 - prev.y1 > 1.3 * max(prev.cap, r.cap):
                paras.append([r])
            else:
                paras[-1].append(r)
        for k, para in enumerate(paras):
            cand = Cand(zone.name, [_shift(r, zx0, zy0) for r in para], True,
                        "right" if len(para) > 1 else "left", panel_bgr=bgr)
            cand.head = k == 0 and len(paras) > 1 and len(para) == 1
            cands.append(cand)
    return cands


def find_all(frame: np.ndarray, zones: tuple[Zone, ...], p: FindParams | None = None,
             exclude: tuple[tuple[int, int, int, int], ...] = ()) -> list[Cand]:
    """Messages first (their text is read as paragraphs), then the rows of every zone around them.
    `exclude`: boxes (frame pixels) never searched, the subtitles' own place."""
    p = p or FindParams()
    cards = [c for zone in zones if zone.cards for c in find_cards(frame, zone, p)]
    cards = [c for c in cards if not any(cover(c.box, e) > 0.5 for e in exclude)]
    rows = [c for zone in zones if zone.items for c in find_items(frame, zone, p, skip=list(exclude))]
    # Both are kept where they overlap; the reader settles it (screen_text.py): white letters
    # with a dark edge (the prompts beside a person) over bright sand also look like a message
    # from their edges alone, and the light gaps between a message's lines look like letters.
    return cards + rows


def cover(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    """How much of the smaller of two boxes the other one covers."""
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return inter / small if small > 0 else 0.0


def cand_iou(a: Cand, b: Cand) -> float:
    """Overlap of two found texts' boxes."""
    ax0, ay0, ax1, ay1 = a.box
    bx0, by0, bx1, by1 = b.box
    x0, y0, x1, y1 = max(ax0, bx0), max(ay0, by0), min(ax1, bx1), min(ay1, by1)
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    union = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / union if union else 0.0


def box_iou(a: Item, b: Item) -> float:
    """Overlap of two items' boxes."""
    x0, y0 = max(a.x0, b.x0), max(a.y0, b.y0)
    x1, y1 = min(a.x1, b.x1), min(a.y1, b.y1)
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    union = a.w * a.h + b.w * b.h - inter
    return inter / union if union else 0.0


def mask_iou(a: Item, b: Item) -> float:
    """Overlap of two items' strokes, in frame coordinates (the same text in the same place: ~1)."""
    x0, y0 = min(a.x0, b.x0), min(a.y0, b.y0)
    x1, y1 = max(a.x1, b.x1), max(a.y1, b.y1)
    ca = np.zeros((y1 - y0, x1 - x0), dtype=bool)
    cb = np.zeros_like(ca)
    ca[a.y0 - y0:a.y1 - y0, a.x0 - x0:a.x1 - x0] = a.mask > 0
    cb[b.y0 - y0:b.y1 - y0, b.x0 - x0:b.x1 - x0] = b.mask > 0
    union = np.logical_or(ca, cb).sum()
    return float(np.logical_and(ca, cb).sum() / union) if union else 0.0
