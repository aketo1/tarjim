"""Draw the Tarjim mark and write every icon file from it.

The mark is the Arabic letter teh (the first letter of "ترجم") in moonlight white,
its two dots in the colours of dawn, on a tile of night sky over the dunes: the same
"desert night" as the app's own look.

    python launcher/make_icon.py

Writes: tarjim/app/web/icon.png, icon.ico, mark.png (the letter alone, transparent),
the Android launcher icons of the TV app and the companion phone app, the TV banner,
and, when it sits next to this repo, the standalone phone app's icons.
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
PHONE = REPO.parent / "tarjim-android" / "tarjim-phone" / "android" / "app" / "src" / "main"

PAPER = (251, 246, 236)
DAWN = ((255, 224, 138), (255, 109, 109))  # gold to coral, as the app's buttons
SKY = ((8, 11, 36), (27, 22, 70), (74, 36, 82))  # top, middle, horizon
DUNES = ((46, 26, 66), (21, 13, 37))


def letter(size: int) -> Image.Image:
    """The teh, moonlight white with dawn-coloured dots, tightly cropped, on transparent."""
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
    h, w = mask.shape
    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[..., :3] = PAPER
    # the dots: a diagonal sweep from gold to coral
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    t = np.clip((xx / max(1, w - 1)) * 0.6 + (yy / max(1, h - 1)) * 0.4, 0, 1)[..., None]
    sweep = (np.array(DAWN[0], np.float32) * (1 - t) + np.array(DAWN[1], np.float32) * t).astype(np.uint8)
    rgba[dots, :3] = sweep[dots]
    rgba[..., 3] = mask
    return Image.fromarray(rgba, "RGBA")


def _sky(big: int) -> Image.Image:
    yy, xx = np.mgrid[0:big, 0:big].astype(np.float32) / big
    top, mid, low = (np.array(c, np.float32) for c in SKY)
    a = np.clip(yy / 0.55, 0, 1)[..., None]
    b = np.clip((yy - 0.55) / 0.45, 0, 1)[..., None]
    base = top * (1 - a) + mid * a
    base = base * (1 - b) + low * b
    # dawn rising behind the dunes, a little to one side
    glow = np.exp(-(((xx - 0.62) / 0.42) ** 2 + ((yy - 1.0) / 0.34) ** 2))[..., None]
    base += (np.array((255, 150, 96), np.float32) - base) * 0.55 * glow
    img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    draw = ImageDraw.Draw(img)
    rng = np.random.default_rng(1117)
    for _ in range(46):
        x, y = rng.random() * big, (rng.random() ** 1.6) * big * 0.55
        r = big * (0.0016 + rng.random() * 0.003)
        a8 = int(110 + rng.random() * 145)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(240, 236, 255, a8))
    # two layers of dunes along the bottom
    for i, (colour, base_y, amp) in enumerate(((DUNES[0], 0.86, 0.05), (DUNES[1], 0.93, 0.035))):
        pts = []
        for k in range(0, 101):
            x = k / 100
            y = base_y - amp * (np.sin((x * 2.4 + i * 0.7) * np.pi) * 0.6 + np.sin((x * 5.1 + i) * np.pi) * 0.25)
            pts.append((x * big, y * big))
        draw.polygon(pts + [(big, big), (0, big)], fill=(*colour, 255))
    return img


def tile(size: int, rounded: bool = True, pad: float = 0.21) -> Image.Image:
    """The full icon. `rounded=False` gives a full-bleed square (Android adaptive background + mark)."""
    scale = 4
    big = size * scale
    img = _sky(big)
    mark = letter(big)
    target = int(big * (1 - 2 * pad))
    ratio = min(target / mark.width, target / mark.height)
    mark = mark.resize((max(1, int(mark.width * ratio)), max(1, int(mark.height * ratio))), Image.LANCZOS)
    x, y = (big - mark.width) // 2, (big - mark.height) // 2 - int(big * 0.02)
    # a soft moonlight glow around the letter, then its shadow, then the letter
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    glow.paste((255, 236, 200, 120), (x, y), mark.split()[3])
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(big * 0.045)))
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow.paste((6, 4, 20, 170), (x, y + int(big * 0.018)), mark.split()[3])
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(big * 0.018)))
    img.alpha_composite(mark, (x, y))
    if rounded:
        radius = int(big * 0.225)
        # glass rim: a thin light along the top edge of the tile
        rim = Image.new("L", (big, big), 0)
        ImageDraw.Draw(rim).rounded_rectangle((2, 2, big - 3, big - 3), radius=radius, outline=255, width=max(2, big // 160))
        fade = np.linspace(0.42, 0.04, big, dtype=np.float32)[:, None]
        rim_a = (np.asarray(rim, np.float32) * fade).astype(np.uint8)
        light = Image.new("RGBA", (big, big), (255, 255, 255, 0))
        light.putalpha(Image.fromarray(rim_a, "L"))
        img.alpha_composite(light)
        corner = Image.new("L", (big, big), 0)
        ImageDraw.Draw(corner).rounded_rectangle((0, 0, big - 1, big - 1), radius=radius, fill=255)
        img.putalpha(corner)
    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    tile(512).save(WEB / "icon.png")
    tile(256).save(WEB / "icon.ico", sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)])
    mark = letter(360)
    mark.save(WEB / "mark.png")
    launchers = [
        (REPO / "tv-app" / "app" / "src" / "main" / "res", {"xhdpi": 96, "xxhdpi": 144}),
        (REPO / "phone-app" / "app" / "src" / "main" / "res", {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}),
        (PHONE / "res", {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}),
    ]
    for res, sizes in launchers:
        if not res.exists():
            continue
        for density, px in sizes.items():
            folder = res / f"mipmap-{density}"
            folder.mkdir(parents=True, exist_ok=True)
            tile(px).save(folder / "ic_launcher.png")
    if (PHONE / "assets" / "web").exists():
        tile(512).save(PHONE / "assets" / "web" / "icon.png")
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
