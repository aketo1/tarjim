"""Draw the Tarjim mark and write every icon file from it.

The mark is the Arabic letter teh (the first letter of "ترجم") in warm white,
its two dots in subtitle amber, on a near-black tile.

    python launcher/make_icon.py

Writes: tarjim/app/web/icon.png, icon.ico, mark.png (the letter alone, transparent),
and the Android launcher icons of the TV app and the phone app.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

LAPTOP = Path(__file__).resolve().parents[1]
REPO = LAPTOP.parent
FONT = REPO / "fonts" / "NotoSansArabic-VF.ttf"
WEB = LAPTOP / "tarjim" / "app" / "web"

INK = (10, 11, 15)
INK_2 = (24, 26, 36)
PAPER = (243, 241, 234)
AMBER = (255, 194, 51)


def letter(size: int) -> Image.Image:
    """The teh, white with amber dots, tightly cropped, on transparent."""
    font = ImageFont.truetype(str(FONT), int(size * 1.2))
    font.set_variation_by_axes([900, 100])
    canvas = Image.new("L", (size * 3, size * 3), 0)
    ImageDraw.Draw(canvas).text((size * 1.5, size * 1.5), "ت", font=font, fill=255, anchor="mm")
    mask = np.asarray(canvas)
    ys, xs = np.nonzero(mask > 8)
    mask = mask[ys.min(): ys.max() + 1, xs.min(): xs.max() + 1]
    count, labels, stats, _ = cv2.connectedComponentsWithStats((mask > 100).astype(np.uint8), connectivity=8)
    order = sorted(range(1, count), key=lambda i: stats[i, cv2.CC_STAT_AREA])
    dots = np.isin(labels, order[:-1])  # everything except the bowl
    dots = cv2.dilate(dots.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    rgba = np.zeros((*mask.shape, 4), np.uint8)
    rgba[..., :3] = PAPER
    rgba[dots, :3] = AMBER
    rgba[..., 3] = mask
    return Image.fromarray(rgba, "RGBA")


def tile(size: int, rounded: bool = True, pad: float = 0.2) -> Image.Image:
    """The full icon. `rounded=False` gives a full-bleed square (Android adaptive background + mark)."""
    scale = 4
    big = size * scale
    yy, xx = np.mgrid[0:big, 0:big].astype(np.float32) / big
    glow = np.exp(-(((xx - 0.72) / 0.5) ** 2 + ((yy - 0.18) / 0.45) ** 2))
    base = np.zeros((big, big, 3), np.float32)
    for c in range(3):
        base[..., c] = INK[c] + (INK_2[c] - INK[c]) * (1 - yy) + (AMBER[c] - INK[c]) * 0.13 * glow
    img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    mark = letter(big)
    target = int(big * (1 - 2 * pad))
    ratio = min(target / mark.width, target / mark.height)
    mark = mark.resize((max(1, int(mark.width * ratio)), max(1, int(mark.height * ratio))), Image.LANCZOS)
    x, y = (big - mark.width) // 2, (big - mark.height) // 2 + int(big * 0.015)
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 150), (x, y + int(big * 0.02)), mark.split()[3])
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(big * 0.02)))
    img.alpha_composite(mark, (x, y))
    if rounded:
        corner = Image.new("L", (big, big), 0)
        ImageDraw.Draw(corner).rounded_rectangle((0, 0, big - 1, big - 1), radius=int(big * 0.225), fill=255)
        img.putalpha(corner)
    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    tile(512).save(WEB / "icon.png")
    tile(256).save(WEB / "icon.ico", sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)])
    mark = letter(360)
    mark.save(WEB / "mark.png")
    for app, sizes in (("tv-app", {"xhdpi": 96, "xxhdpi": 144}), ("phone-app", {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192})):
        res = REPO / app / "app" / "src" / "main" / "res"
        if not res.parent.exists():
            continue
        for density, px in sizes.items():
            folder = res / f"mipmap-{density}"
            folder.mkdir(parents=True, exist_ok=True)
            tile(px).save(folder / "ic_launcher.png")
    # Android TV home-screen banner, 320x180.
    banner_dir = REPO / "tv-app" / "app" / "src" / "main" / "res" / "drawable-xhdpi"
    if banner_dir.parent.exists():
        banner_dir.mkdir(parents=True, exist_ok=True)
        wide = tile(640, rounded=False, pad=0.5).crop((0, 140, 640, 500))
        small = letter(400)
        ratio = 150 / small.height
        small = small.resize((int(small.width * ratio), 150), Image.LANCZOS)
        wide.alpha_composite(small, (640 - small.width - 70, 80))
        latin = ImageFont.truetype(str(REPO / "fonts" / "NotoSans-VF.ttf"), 64)
        latin.set_variation_by_axes([700, 100])
        ImageDraw.Draw(wide).text((70, 180), "Tarjim", font=latin, fill=PAPER, anchor="lm")
        wide.convert("RGB").save(banner_dir / "banner.png")
    print("icons written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
