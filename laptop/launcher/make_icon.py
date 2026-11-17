"""Draw the Tarjim mark and write every icon file from it.

The mark is the Arabic letter teh (the first letter of "ترجم") in near-black on a white
tile: the same white square with the black letter that sits at the corner of the app's
own page, which leaves all colour to the games.

    python launcher/make_icon.py

Writes: tarjim/app/web/icon.png, icon.ico, mark.png (the letter alone, transparent),
the Android launcher icons of the TV app and the companion phone app, the TV banner,
and, when it sits next to this repo, the standalone phone app's icons.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

LAPTOP = Path(__file__).resolve().parents[1]
REPO = LAPTOP.parent
FONT = REPO / "fonts" / "NotoSansArabic-VF.ttf"
WEB = LAPTOP / "tarjim" / "app" / "web"
PHONE = REPO.parent / "tarjim-android" / "tarjim-phone" / "android" / "app" / "src" / "main"

INK = (17, 17, 19)


def letter(size: int, colour: tuple[int, int, int] = INK) -> Image.Image:
    """The teh in one colour, tightly cropped, on transparent."""
    font = ImageFont.truetype(str(FONT), int(size * 1.2))
    font.set_variation_by_axes([900, 100])
    canvas = Image.new("L", (size * 3, size * 3), 0)
    ImageDraw.Draw(canvas).text((size * 1.5, size * 1.5), "ت", font=font, fill=255, anchor="mm")
    mask = np.asarray(canvas)
    ys, xs = np.nonzero(mask > 8)
    mask = mask[ys.min(): ys.max() + 1, xs.min(): xs.max() + 1]
    rgba = np.zeros((*mask.shape, 4), np.uint8)
    rgba[..., :3] = colour
    rgba[..., 3] = mask
    return Image.fromarray(rgba, "RGBA")


def tile(size: int, rounded: bool = True, pad: float = 0.2) -> Image.Image:
    """The full icon. `rounded=False` gives a full-bleed square (for the TV banner)."""
    scale = 4
    big = size * scale
    # a white face, a touch darker towards the bottom, like a card under a lamp
    shade = np.linspace(255, 236, big, dtype=np.float32)[:, None, None]
    face = np.broadcast_to(shade, (big, big, 3)).astype(np.uint8)
    img = Image.fromarray(np.ascontiguousarray(face), "RGB").convert("RGBA")
    mark = letter(big)
    target = int(big * (1 - 2 * pad))
    ratio = min(target / mark.width, target / mark.height)
    mark = mark.resize((max(1, int(mark.width * ratio)), max(1, int(mark.height * ratio))), Image.LANCZOS)
    x, y = (big - mark.width) // 2, (big - mark.height) // 2 - int(big * 0.02)
    img.alpha_composite(mark, (x, y))
    if rounded:
        radius = int(big * 0.225)
        # a hairline edge, so the white tile keeps its shape on a white desktop
        edge = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        ImageDraw.Draw(edge).rounded_rectangle((1, 1, big - 2, big - 2), radius=radius, outline=(0, 0, 0, 34), width=max(2, big // 200))
        img.alpha_composite(edge)
        corner = Image.new("L", (big, big), 0)
        ImageDraw.Draw(corner).rounded_rectangle((0, 0, big - 1, big - 1), radius=radius, fill=255)
        img.putalpha(corner)
    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    tile(512).save(WEB / "icon.png")
    tile(256).save(WEB / "icon.ico", sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)])
    letter(360).save(WEB / "mark.png")
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
    # Android TV home-screen banner, 320x180: the letter and the name in black on white.
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
        ImageDraw.Draw(wide).text((70, 180), "Tarjim", font=latin, fill=INK, anchor="lm")
        wide.convert("RGB").save(banner_dir / "banner.png")
    print("icons written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
