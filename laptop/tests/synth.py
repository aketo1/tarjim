"""Synthetic subtitle frames with ground truth, for the detection/OCR/erase tests.

The dialogue below is written for these tests; it is not taken from any game.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT = Path(__file__).resolve().parents[2] / "fonts" / "NotoSans-VF.ttf"

LINES = [
    "We should leave before the storm gets here.",
    "I never asked you to follow me.",
    "The bridge is out. We go around.",
    "Did you hear that? Something moved.",
    "Keep your voice down and stay close.",
    "My father built this house with his own hands.",
    "You have ten minutes. Make them count.",
    "There is no map for where we are going.",
    "I told you the truth, and you laughed.",
    "Hold the lantern higher, I can't see a thing.",
    "Nobody comes back from the northern road.",
    "She left a letter. It is addressed to you.",
    "We are out of water, out of time, and out of luck.",
    "Trust me, this is the quiet part of town.",
    "If the engine stalls again, we walk.",
    "That door was locked when we arrived.",
]
TWO_LINES = [
    ("Now listen carefully, because I will", "not say any of this a second time."),
    ("They promised us a ship by morning,", "and all we got was this broken raft."),
    ("Every winter the river freezes over", "and the whole valley goes silent."),
    ("I have walked this road for thirty years", "and it has never looked like this."),
]


@dataclass
class Sample:
    frame: np.ndarray  # BGR 1920x1080
    text: str | None  # joined ground-truth text, None when the frame has no subtitle
    lines: list[str]
    bbox: tuple[int, int, int, int] | None  # x0, y0, x1, y1 of the text
    style: str


def background(rng: np.random.Generator, kind: str) -> np.ndarray:
    h, w = 1080, 1920
    if kind == "dark":
        base = rng.integers(8, 40, size=(h // 40, w // 40, 3)).astype(np.float32)
    elif kind == "bright":
        base = rng.integers(140, 215, size=(h // 40, w // 40, 3)).astype(np.float32)
    else:  # "scene": mixed light and dark regions
        base = rng.integers(10, 190, size=(h // 60, w // 60, 3)).astype(np.float32)
    img = cv2.resize(base, (w, h), interpolation=cv2.INTER_CUBIC)
    img += rng.normal(0, 3.0, size=img.shape)  # film grain
    if kind == "scene":
        # A few soft bright blobs (lamps, windows) in the lower part of the picture.
        for _ in range(4):
            cx, cy = int(rng.integers(100, w - 100)), int(rng.integers(700, 1060))
            r = int(rng.integers(30, 90))
            blob = np.zeros((h, w), np.float32)
            cv2.circle(blob, (cx, cy), r, 1.0, -1)
            blob = cv2.GaussianBlur(blob, (0, 0), r / 2.0)
            img += blob[:, :, None] * float(rng.integers(40, 90))
    return np.clip(img, 0, 255).astype(np.uint8)


def draw_subtitle(bgr: np.ndarray, lines: list[str], style: str, size: int, bottom: int) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    font = ImageFont.truetype(str(FONT), size)
    img = Image.fromarray(bgr[:, :, ::-1])
    pitch = int(size * 1.35)
    boxes = []
    layout = []
    probe = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        w = probe.textlength(line, font=font)
        x = int(round((1920 - w) / 2))
        y = bottom - pitch * (len(lines) - i)
        layout.append((x, y, line))
        boxes.append(probe.textbbox((x, y), line, font=font))
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    if style == "boxed":
        bar = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(bar).rectangle([x0 - 24, y0 - 12, x1 + 24, y1 + 12], fill=(0, 0, 0, 185))
        img = Image.alpha_composite(img.convert("RGBA"), bar).convert("RGB")
    elif style == "shadow":
        sh = Image.new("L", img.size, 0)
        d = ImageDraw.Draw(sh)
        for x, y, line in layout:
            d.text((x + 2, y + 2), line, font=font, fill=230)
        sh = sh.filter(ImageFilter.GaussianBlur(2.2))
        img = Image.composite(Image.new("RGB", img.size, (0, 0, 0)), img, sh)
    d = ImageDraw.Draw(img)
    for x, y, line in layout:
        if style == "outline":
            d.text((x, y), line, font=font, fill=(245, 245, 245), stroke_width=2, stroke_fill=(0, 0, 0))
        else:
            d.text((x, y), line, font=font, fill=(242, 247, 241))
    return np.ascontiguousarray(np.asarray(img)[:, :, ::-1]), (x0, y0, x1, y1)


def make_samples(n_text: int, n_empty: int, seed: int = 7) -> list[Sample]:
    rng = np.random.default_rng(seed)
    styles = ["shadow", "outline", "boxed"]
    kinds = ["dark", "scene", "bright"]
    out: list[Sample] = []
    for i in range(n_text):
        style = styles[i % 3]
        kind = kinds[(i // 3) % 3]
        if style != "boxed" and kind == "bright":
            kind = "scene"  # unboxed white text over a bright picture is not readable by people either
        if i % 4 == 3:
            lines = list(TWO_LINES[(i // 4) % len(TWO_LINES)])
        else:
            lines = [LINES[i % len(LINES)]]
        size = int(rng.choice([34, 38, 42, 46]))
        bottom = int(rng.integers(940, 1030))
        frame, bbox = draw_subtitle(background(rng, kind), lines, style, size, bottom)
        out.append(Sample(frame, " ".join(lines), lines, bbox, style))
    for i in range(n_empty):
        out.append(Sample(background(rng, kinds[i % 3]), None, [], None, "none"))
    return out


def typewriter_frames(line: str, frames_per_char: int = 1, hold: int = 12, seed: int = 3) -> list[np.ndarray]:
    """The line appears one character at a time, then holds."""
    rng = np.random.default_rng(seed)
    bg = background(rng, "dark")
    font = ImageFont.truetype(str(FONT), 40)
    x = int(round((1920 - ImageDraw.Draw(Image.new("RGB", (8, 8))).textlength(line, font=font)) / 2))
    frames = []
    for n in list(range(1, len(line) + 1)) + [len(line)] * hold:
        img = Image.fromarray(bg[:, :, ::-1])
        ImageDraw.Draw(img).text((x, 950), line[:n], font=font, fill=(242, 247, 241))
        frame = np.ascontiguousarray(np.asarray(img)[:, :, ::-1])
        frames.extend([frame] * frames_per_char)
    return frames
