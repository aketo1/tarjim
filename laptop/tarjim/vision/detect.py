"""Find the subtitle block in a frame: a stroke mask of light, thin text.

Model `bright-thin` from the brief: white top-hat on min(R,G,B), threshold,
connected components, keep glyph-sized blobs that line up in rows. All sizes
scale with frame height (reference: 1080p).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass(frozen=True)
class DetectParams:
    roi_top: float = 0.70  # ROI = bottom 30% of the frame ...
    roi_side: float = 0.08  # ... and the central 84% of its width
    # A user-drawn region overrides the defaults above (fractions of the frame, 0..1).
    roi_bottom: float = 1.0
    roi_left: float | None = None
    roi_right: float | None = None
    tophat_kernel: int = 15
    tophat_min: int = 45
    bright_min: int = 150
    glyph_h_min: int = 9
    glyph_h_max: int = 44
    min_glyphs_per_line: int = 4
    min_line_width: int = 60
    max_lines: int = 3


@dataclass
class Line:
    x0: int
    y0: int
    x1: int
    y1: int  # exclusive
    glyphs: int


@dataclass
class Block:
    """A detected subtitle block. Coordinates are frame pixels; x1/y1 exclusive."""

    x0: int
    y0: int
    x1: int
    y1: int
    mask: np.ndarray  # uint8 0/255, shape (y1-y0, x1-x0): the letter strokes
    lines: list[Line] = field(default_factory=list)

    @property
    def w(self) -> int:
        return self.x1 - self.x0

    @property
    def h(self) -> int:
        return self.y1 - self.y0

    @property
    def glyphs(self) -> int:
        return sum(l.glyphs for l in self.lines)


def _odd(v: float) -> int:
    n = max(3, int(round(v)))
    return n if n % 2 else n + 1


def candidate_mask(roi_bgr: np.ndarray, p: DetectParams, s: float) -> np.ndarray:
    """Pixels that look like light, thin strokes (uint8 0/255)."""
    # cv2.min is ~8x faster than numpy's min over the channel axis; a square
    # kernel is separable and ~6x faster than the ellipse, with the same result
    # for strokes this thin.
    m = cv2.min(cv2.min(roi_bgr[:, :, 0], roi_bgr[:, :, 1]), roi_bgr[:, :, 2])
    k = _odd(p.tophat_kernel * s)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    tophat = cv2.morphologyEx(m, cv2.MORPH_TOPHAT, kernel)
    return ((tophat > p.tophat_min) & (m > p.bright_min)).astype(np.uint8) * 255


def _chains(items: list[tuple[int, int, int, int, int]], max_gap: float) -> list[list[tuple[int, int, int, int, int]]]:
    """Split components (sorted by x) wherever the horizontal gap is too large."""
    out: list[list] = []
    cur: list = []
    right = None
    for it in items:
        x, _y, w, _h, _i = it
        if right is not None and x - right > max_gap:
            out.append(cur)
            cur = []
        cur.append(it)
        right = x + w if right is None or not cur[:-1] else max(right, x + w)
    if cur:
        out.append(cur)
    return out


def detect(frame_bgr: np.ndarray, params: DetectParams | None = None) -> Block | None:
    p = params or DetectParams()
    fh, fw = frame_bgr.shape[:2]
    s = fh / 1080.0
    ry0 = int(fh * p.roi_top)
    ry1 = max(ry0 + 8, min(fh, int(round(fh * p.roi_bottom))))
    rx0 = int(fw * (p.roi_side if p.roi_left is None else p.roi_left))
    rx1 = fw - int(fw * p.roi_side) if p.roi_right is None else int(round(fw * p.roi_right))
    rx1 = max(rx0 + 8, min(fw, rx1))
    roi = np.ascontiguousarray(frame_bgr[ry0:ry1, rx0:rx1])
    cand = candidate_mask(roi, p, s)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(cand, connectivity=8)
    if n <= 1:
        return None
    h_min, h_max = p.glyph_h_min * s, p.glyph_h_max * s
    glyphs = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if h_min <= h <= h_max and w <= 3.0 * h_max and area >= 12 * s * s:
            glyphs.append((int(x), int(y), int(w), int(h), i))
    if len(glyphs) < p.min_glyphs_per_line:
        return None

    # Rows: bands of the horizontal projection of glyph centres.
    profile = np.zeros(roi.shape[0], dtype=np.int32)
    for x, y, w, h, _ in glyphs:
        profile[y : y + h] += 1
    rows = []
    start = None
    for yy, v in enumerate(profile):
        if v >= 2 and start is None:
            start = yy
        elif v < 2 and start is not None:
            rows.append((start, yy))
            start = None
    if start is not None:
        rows.append((start, len(profile)))

    lines: list[tuple[Line, list[int]]] = []
    for r0, r1 in rows:
        if r1 - r0 < h_min or r1 - r0 > 1.8 * h_max:
            continue
        members = sorted(g for g in glyphs if r0 <= g[1] + g[3] / 2 < r1)
        if len(members) < p.min_glyphs_per_line:
            continue
        med_h = float(np.median([g[3] for g in members]))
        members = [g for g in members if 0.3 * med_h <= g[3] <= 1.7 * med_h]
        chains = _chains(members, max_gap=2.2 * med_h)
        best = max(chains, key=len, default=[])
        if len(best) < p.min_glyphs_per_line:
            continue
        # Letters over a bright patch of the scene fail the top-hat test and
        # split one sentence into pieces. Rejoin neighbouring pieces of the same
        # row (the gap is a few lost letters, not a different text).
        idx = chains.index(best)
        joined = list(best)
        left = min(g[0] for g in joined)
        for c in reversed(chains[:idx]):
            if len(c) < 2 or left - max(g[0] + g[2] for g in c) > 7.0 * med_h:
                break
            joined = c + joined
            left = min(g[0] for g in c)
        right = max(g[0] + g[2] for g in joined)
        for c in chains[idx + 1 :]:
            if len(c) < 2 or min(g[0] for g in c) - right > 7.0 * med_h:
                break
            joined = joined + c
            right = max(g[0] + g[2] for g in c)
        best = joined
        x0 = min(g[0] for g in best)
        x1 = max(g[0] + g[2] for g in best)
        if x1 - x0 < p.min_line_width * s:
            continue
        y0 = min(g[1] for g in best)
        y1 = max(g[1] + g[3] for g in best)
        lines.append((Line(x0, y0, x1, y1, len(best)), [g[4] for g in best]))
    if not lines:
        return None

    # Group vertically adjacent lines of similar height; keep the group with most glyphs.
    lines.sort(key=lambda t: t[0].y0)
    groups: list[list[tuple[Line, list[int]]]] = []
    for item in lines:
        ln = item[0]
        if groups:
            prev = groups[-1][-1][0]
            ph, lh = prev.y1 - prev.y0, ln.y1 - ln.y0
            close = ln.y0 - prev.y1 <= 1.3 * max(ph, lh)
            similar = 0.6 <= lh / ph <= 1.67
            overlap = min(prev.x1, ln.x1) - max(prev.x0, ln.x0) > 0
            if close and similar and overlap and len(groups[-1]) < p.max_lines:
                groups[-1].append(item)
                continue
        groups.append([item])
    group = max(groups, key=lambda g: sum(t[0].glyphs for t in g))

    bx0 = min(t[0].x0 for t in group)
    bx1 = max(t[0].x1 for t in group)
    by0 = min(t[0].y0 for t in group)
    by1 = max(t[0].y1 for t in group)
    line_h = float(np.median([t[0].y1 - t[0].y0 for t in group]))
    pad = int(round(0.45 * line_h))
    bx0, by0 = max(0, bx0 - pad), max(0, by0 - pad)
    bx1, by1 = min(roi.shape[1], bx1 + pad), min(roi.shape[0], by1 + pad)

    # Mask: the chosen glyphs plus small marks (dots, commas, accents) inside their line bands.
    keep = np.zeros(n, dtype=bool)
    for _, ids in group:
        keep[ids] = True
    for i in range(1, n):
        if keep[i]:
            continue
        x, y, w, h, area = stats[i]
        if area < 2 or h > h_max or w > 3 * h_max:
            continue
        cx, cy = x + w / 2, y + h / 2
        for ln, _ in group:
            if ln.y0 - 0.5 * line_h <= cy <= ln.y1 + 0.5 * line_h and ln.x0 - line_h <= cx <= ln.x1 + line_h:
                keep[i] = True
                break
    mask = (keep[labels[by0:by1, bx0:bx1]]).astype(np.uint8) * 255

    out_lines = [
        Line(t[0].x0 + rx0, t[0].y0 + ry0, t[0].x1 + rx0, t[0].y1 + ry0, t[0].glyphs) for t in group
    ]
    return Block(bx0 + rx0, by0 + ry0, bx1 + rx0, by1 + ry0, mask, out_lines)


def mask_iou(a: Block | None, b: Block | None) -> float:
    """IoU of two blocks' stroke masks in frame coordinates."""
    if a is None or b is None:
        return 0.0
    x0, y0 = min(a.x0, b.x0), min(a.y0, b.y0)
    x1, y1 = max(a.x1, b.x1), max(a.y1, b.y1)
    ca = np.zeros((y1 - y0, x1 - x0), dtype=bool)
    cb = np.zeros_like(ca)
    ca[a.y0 - y0 : a.y1 - y0, a.x0 - x0 : a.x1 - x0] = a.mask > 0
    cb[b.y0 - y0 : b.y1 - y0, b.x0 - x0 : b.x1 - x0] = b.mask > 0
    union = np.logical_or(ca, cb).sum()
    return float(np.logical_and(ca, cb).sum() / union) if union else 0.0
