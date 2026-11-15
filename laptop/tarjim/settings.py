"""Turn a game profile (YAML dict) into renderer and pipeline settings. One place, used by
the command line, the app's live session and the app's preview."""

from __future__ import annotations

from .vision import render
from .vision.arabic import FONT_FILES
from .vision.detect import DetectParams

DEFAULT_REGION = {"left": 0.08, "top": 0.70, "right": 0.92, "bottom": 1.0}

BACKGROUNDS = ("cover", "plate", "none")
EFFECTS = ("shadow", "outline", "none")


def parse_color(value) -> tuple[int, int, int] | None:
    """'#rrggbb' -> (b, g, r) for OpenCV; anything else (including 'auto') -> None."""
    if not isinstance(value, str):
        return None
    v = value.strip().lstrip("#")
    if len(v) != 6:
        return None
    try:
        r, g, b = int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
    except ValueError:
        return None
    return (b, g, r)


def background(profile: dict) -> str:
    mode = profile.get("background")
    if mode in BACKGROUNDS:
        return mode
    return "cover" if profile.get("fill", True) else "none"  # older profiles only had `fill`


def plate_opacity(profile: dict) -> float:
    try:
        return max(0.2, min(0.95, float(profile.get("plate_opacity", 0.62))))
    except (TypeError, ValueError):
        return 0.62


def make_style(profile: dict, remembered_size: int | None = None) -> render.Style:
    font = profile.get("font", "harmattan")
    size = profile.get("font_size") or remembered_size
    effect = profile.get("effect", "shadow")
    try:
        offset = max(-300, min(120, int(profile.get("y_offset", 0))))
    except (TypeError, ValueError):
        offset = 0
    return render.Style(
        font=font if font in FONT_FILES else "harmattan",
        fixed_size=int(size) if size else None,
        color=parse_color(profile.get("text_color")),
        effect=effect if effect in EFFECTS else "shadow",
        y_offset=offset,
    )


def region(profile: dict) -> dict:
    """Where on the screen subtitles are looked for, as fractions of the frame. Always valid."""
    raw = profile.get("region")
    out = dict(DEFAULT_REGION)
    if isinstance(raw, dict):
        for key in out:
            try:
                out[key] = float(raw[key])
            except (KeyError, TypeError, ValueError):
                return dict(DEFAULT_REGION)
    left, top = max(0.0, min(0.9, out["left"])), max(0.0, min(0.92, out["top"]))
    right, bottom = max(left + 0.1, min(1.0, out["right"])), max(top + 0.08, min(1.0, out["bottom"]))
    return {"left": round(left, 4), "top": round(top, 4), "right": round(right, 4), "bottom": round(bottom, 4)}


def detect_params(profile: dict) -> DetectParams:
    r = region(profile)
    return DetectParams(roi_top=r["top"], roi_bottom=r["bottom"], roi_left=r["left"], roi_right=r["right"])
