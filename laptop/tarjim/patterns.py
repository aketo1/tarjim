"""Test patterns for `tarjim tv test` and the screencap self-check."""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from .protocol import Layer


@dataclass(frozen=True)
class Pattern:
    win: str
    label: str
    color: tuple[int, int, int]
    x: int
    y: int
    w: int
    h: int

    def probe_points(self) -> list[tuple[int, int]]:
        """Overlay-pixel points that are solid `color` (inside the border, away from the letter)."""
        inset = 30
        return [
            (self.x + inset, self.y + inset),
            (self.x + self.w - inset, self.y + inset),
            (self.x + inset, self.y + self.h - inset),
            (self.x + self.w - inset, self.y + self.h - inset),
        ]


def make_patterns(overlay_w: int, overlay_h: int) -> dict[str, Pattern]:
    """A on the left in magenta, B on the right in cyan; both vertically centred."""
    w = round(overlay_w * 0.30)
    h = min(round(overlay_h * 0.28), 480)
    y = (overlay_h - h) // 2
    return {
        "A": Pattern("A", "A", (230, 0, 160), round(overlay_w * 0.12), y, w, h),
        "B": Pattern("B", "B", (0, 200, 230), round(overlay_w * 0.58), y, w, h),
    }


def render_pattern(p: Pattern) -> bytes:
    img = Image.new("RGBA", (p.w, p.h), p.color + (255,))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, p.w - 1, p.h - 1], outline=(255, 255, 255, 255), width=8)
    font = ImageFont.load_default(size=int(p.h * 0.6))
    box = draw.textbbox((0, 0), p.label, font=font)
    tx = (p.w - (box[2] - box[0])) // 2 - box[0]
    ty = (p.h - (box[3] - box[1])) // 2 - box[1]
    draw.text((tx + 4, ty + 4), p.label, font=font, fill=(0, 0, 0, 255))
    draw.text((tx, ty), p.label, font=font, fill=(255, 255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=1)
    return buf.getvalue()


def pattern_layer(p: Pattern, ttl_ms: int = 1000) -> Layer:
    return Layer(id=f"pattern-{p.win}", png=render_pattern(p), x=p.x, y=p.y, w=p.w, h=p.h, z=0, ttl_ms=ttl_ms)


def check_screencap(shot: Image.Image, overlay_w: int, overlay_h: int, patterns: list[Pattern], tol: int = 40) -> dict:
    """Compare a TV screencap with the patterns we asked the TV to draw.

    Returns {win: {"ok": bool, "points": [(x, y, rgb), ...]}}. The screencap
    may be larger than the overlay plane (4K panel, 1080p UI), so points scale.
    """
    shot = shot.convert("RGB")
    sx = shot.width / overlay_w
    sy = shot.height / overlay_h
    result = {}
    for p in patterns:
        points = []
        ok = True
        for ox, oy in p.probe_points():
            px = min(shot.width - 1, round(ox * sx))
            py = min(shot.height - 1, round(oy * sy))
            rgb = shot.getpixel((px, py))
            points.append((px, py, rgb))
            if max(abs(a - b) for a, b in zip(rgb, p.color)) > tol:
                ok = False
        result[p.win] = {"ok": ok, "points": points}
    return result
