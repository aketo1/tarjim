"""Pictures and animations for the README, made by the program's real code.

    python launcher/make_media.py

- docs/media/swap.gif      a dusk scene with English subtitles; the real detector finds each
                           line and the real renderer replaces it with Arabic (what the TV shows)
- docs/media/before.png, after.png   one frame of the same, side by side material
- docs/media/tour.gif      the app's screens, from the screenshots in out/ (launcher/shots.py)
- docs/media/*.png         copies of the screenshots the README uses
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

LAPTOP = Path(__file__).resolve().parents[1]
REPO = LAPTOP.parent
sys.path.insert(0, str(LAPTOP))
OUT = REPO / "out"
MEDIA = REPO / "docs" / "media"

LINES = [
    ("We should leave before the storm gets here.", "يجب أن نغادر قبل وصول العاصفة."),
    ("Keep your voice down and stay close.", "اخفض صوتك وابقَ قريباً."),
    ("I never thought I'd see this place again.", "لم أظن أنني سأرى هذا المكان مرة أخرى."),
]


def scene(w: int = 1920, h: int = 1080) -> Image.Image:
    """The dusk landscape of the app's home screen, as a 1080p "game" frame."""
    stops = [(0.0, (16, 18, 44)), (0.26, (44, 37, 82)), (0.46, (125, 65, 105)), (0.6, (217, 121, 79)), (0.7, (255, 194, 122)), (1.0, (255, 194, 122))]
    ys = np.linspace(0, 1, h)
    sky = np.zeros((h, w, 3), np.float32)
    for c in range(3):
        sky[..., c] = np.interp(ys, [s[0] for s in stops], [s[1][c] for s in stops])[:, None]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    halo = np.exp(-(((xx - w * 0.7) / 260) ** 2 + ((yy - h * 0.2) / 260) ** 2))
    sky += halo[..., None] * np.array([60, 50, 30], np.float32)
    img = Image.fromarray(np.clip(sky, 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(img)
    draw.ellipse((w * 0.7 - 70, h * 0.2 - 70, w * 0.7 + 70, h * 0.2 + 70), fill=(255, 243, 210))

    def hills(peaks, colour):
        pts = [(-40, h)] + [(-30 + (w + 60) * i / (len(peaks) - 1), h - h * p) for i, p in enumerate(peaks)] + [(w + 40, h)]
        draw.polygon(pts, fill=colour)

    hills([.37, .53, .43, .7, .38, .52, .3, .66, .26, .46, .25, .35], (90, 58, 99))
    hills([.23, .4, .25, .49, .24, .43, .2, .33, .17, .3], (51, 38, 74))
    hills([.13, .25, .15, .3, .14, .26], (21, 18, 31))
    return img


def with_english(base: Image.Image, line: str) -> np.ndarray:
    """Draw a game-style subtitle (white, soft shadow) and return the frame as BGR."""
    img = base.copy()
    font = ImageFont.truetype(str(REPO / "fonts" / "NotoSans-VF.ttf"), 40)
    tw = ImageDraw.Draw(img).textlength(line, font=font)
    x, y = int((img.width - tw) / 2), 940
    shadow = Image.new("L", img.size, 0)
    ImageDraw.Draw(shadow).text((x + 2, y + 2), line, font=font, fill=230)
    img = Image.composite(Image.new("RGB", img.size, (0, 0, 0)), img, shadow.filter(ImageFilter.GaussianBlur(2.2)))
    ImageDraw.Draw(img).text((x, y), line, font=font, fill=(242, 247, 241))
    return np.ascontiguousarray(np.asarray(img)[:, :, ::-1])


def swap() -> None:
    from tarjim.vision import render
    from tarjim.vision.detect import detect

    base = scene()
    style = render.Style(fixed_size=None)
    frames: list[Image.Image] = []
    durations: list[int] = []
    size = (960, 540)

    def add(bgr: np.ndarray, ms: int) -> None:
        frames.append(Image.fromarray(bgr[:, :, ::-1]).resize(size, Image.LANCZOS))
        durations.append(ms)

    for i, (en, ar) in enumerate(LINES):
        frame = with_english(base, en)
        block = detect(frame)
        if block is None:
            raise RuntimeError(f"the detector did not find: {en}")
        after = render.composite(frame, [render.make_fill(frame, block), render.make_text(frame, block, ar, style)])
        if i == 0:
            Image.fromarray(frame[:, :, ::-1]).save(MEDIA / "before.png")
            Image.fromarray(after[:, :, ::-1]).save(MEDIA / "after.png")
        add(frame, 900)
        for k in (1, 2, 3):  # a short blend, like the fade on the TV
            mix = (frame.astype(np.float32) * (1 - k / 4) + after.astype(np.float32) * (k / 4)).astype(np.uint8)
            add(mix, 50)
        add(after, 1900)
        add(np.ascontiguousarray(np.asarray(base)[:, :, ::-1]), 350)
    palette = frames[0].quantize(colors=200, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    paletted = [f.quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG) for f in frames]
    paletted[0].save(MEDIA / "swap.gif", save_all=True, append_images=paletted[1:], duration=durations, loop=0, optimize=True)


def tour() -> None:
    names = ["home", "home-live", "game", "guide1", "m-home"]
    shots = []
    for n in names:
        path = OUT / f"app-{n}.png"
        if not path.exists():
            continue
        img = Image.open(path).convert("RGB")
        img = img.crop((0, 0, img.width, min(img.height, int(img.width * 0.66))))
        canvas = Image.new("RGB", (1000, 660), (10, 11, 15))
        img.thumbnail((1000, 660), Image.LANCZOS)
        canvas.paste(img, ((1000 - img.width) // 2, 0))
        shots.append(canvas)
    if len(shots) < 2:
        print("tour.gif skipped: run launcher/shots.py first")
        return
    palette = shots[1].quantize(colors=160, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    frames = [s.quantize(palette=palette, dither=Image.Dither.NONE) for s in shots]
    frames[0].save(MEDIA / "tour.gif", save_all=True, append_images=frames[1:], duration=2200, loop=0, optimize=True)


def copies() -> None:
    wanted = {"app-home.png": "home.png", "app-home-live.png": "home-live.png", "app-game.png": "look.png",
              "app-m-home.png": "phone-home.png", "app-m-screen.png": "phone-screen.png",
              "setup-welcome.png": "setup.png", "setup-progress.png": "setup-progress.png", "setup-done.png": "setup-done.png"}
    for src, dst in wanted.items():
        path = OUT / src
        if path.exists():
            img = Image.open(path).convert("RGB")
            if dst in ("home-live.png", "look.png"):
                img = img.crop((0, 0, img.width, min(img.height, 1000)))
            img.save(MEDIA / dst, optimize=True)


if __name__ == "__main__":
    MEDIA.mkdir(parents=True, exist_ok=True)
    swap()
    tour()
    copies()
    for f in sorted(MEDIA.iterdir()):
        print(f"{f.name:22s} {f.stat().st_size / 1024:7.0f} KB")
