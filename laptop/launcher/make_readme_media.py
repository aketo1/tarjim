"""The README pictures of both apps, made by the program's own code and pages.

    python launcher/make_readme_media.py [--phone-repo PATH]

Run launcher/shots.py first (the app's pages served at 127.0.0.1:47900); Chrome draws the
banners. Nothing here is mocked up by hand:

- docs/media/hero.gif       the banner: a TV where English game lines turn Arabic. The lines are
                            drawn on the games' own pictures; the real detector finds them, the
                            real engine translates them (with each game's names and words), and
                            the real renderer draws the Arabic.
- docs/media/tour.gif       the app's screens (from shots.py)
- docs/media/phone.gif      the same pages at phone size, in a phone
- docs/media/library.jpg    the covers of the games in the library
- docs/media/*.png          copies of the screenshots the README uses
- <phone repo>/docs/media/  hero.gif (the phone version of the banner), phone.gif, library.jpg and
                            three screenshots
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

LAPTOP = Path(__file__).resolve().parents[1]
REPO = LAPTOP.parent
sys.path.insert(0, str(LAPTOP))
OUT = REPO / "out"
MEDIA = REPO / "docs" / "media"
WEB = LAPTOP / "tarjim" / "app" / "web"
CHROME = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
          r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"]

# (game, English line): the Arabic comes from the engine when this runs.
LINES = [
    ("rdr2", "Take the stolen wagon to the fence."),
    ("gta6", "Lucia, you strapped?"),
    ("rdr2", "Lose the law and meet us at Clemens Point."),
    ("mafia-toc", "He's a made man now, nobody touches him."),
]


def chrome_png(html: str, w: int, h: int) -> Image.Image:
    """Draw an HTML page with Chrome, at exactly w x h pixels."""
    chrome = next(c for c in CHROME if Path(c).exists())
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "page.html"
        page.write_text(html, encoding="utf-8")
        shot = Path(tmp) / "shot.png"
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                        f"--user-data-dir={Path(tmp) / 'profile'}", f"--window-size={w},{h}",
                        "--virtual-time-budget=3000", f"--screenshot={shot}", page.as_uri()],
                       capture_output=True, timeout=90, creationflags=0x08000000)
        return Image.open(shot).convert("RGB").crop((0, 0, w, h))


def translations() -> list[tuple[str, str, str]]:
    """(game, English, Arabic): the engine's own output, with each game's names and words."""
    from tarjim import terms
    from tarjim.translate import Cache, CachedTranslator, OpusTranslator

    engine = OpusTranslator()
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for gid, en in LINES:
            pack = json.loads((REPO / "packs" / f"{gid}.json").read_text(encoding="utf-8"))
            cache = Cache(Path(tmp) / f"{gid}-{len(out)}.sqlite")
            t = CachedTranslator(engine, cache, profile=gid,
                                 glossary={n["en"]: n["ar"] for n in pack["names"]},
                                 female={n["en"] for n in pack["names"] if n.get("f")},
                                 series=terms.series_of(gid))
            out.append((gid, en, t.translate(en)[0]))
            cache.close()
    return out


def scene(gid: str, w: int = 1920, h: int = 1080) -> Image.Image:
    """A 1080p "game" frame from the game's own picture, darker towards the bottom like a film."""
    art = Image.open(WEB / "art" / f"{gid}-bg.webp").convert("RGB")
    cw = min(art.width, int(art.height * w / h))
    x = (art.width - cw) // 2
    img = art.crop((x, 0, x + cw, art.height)).resize((w, h), Image.LANCZOS)
    shade = np.linspace(0, 1, h)[:, None] ** 3 * 0.62
    arr = np.asarray(img).astype(np.float32) * (1 - shade[..., None])
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8))


def with_english(base: Image.Image, line: str, size: int = 44) -> np.ndarray:
    """A game subtitle (white, soft shadow) at a usual size for 1080p; returned as BGR like a
    frame from the console. (At 66 px the detector's block starts about 20 px into the line,
    and above about 50 px the cover leaves bits of the English: see REPORT section 23.)"""
    from PIL import ImageFont

    img = base.copy()
    font = ImageFont.truetype(str(REPO / "fonts" / "NotoSans-VF.ttf"), size)
    tw = ImageDraw.Draw(img).textlength(line, font=font)
    x, y = int((img.width - tw) / 2), img.height - 110 - size
    shadow = Image.new("L", img.size, 0)
    ImageDraw.Draw(shadow).text((x + 2, y + 2), line, font=font, fill=230)
    img = Image.composite(Image.new("RGB", img.size, (0, 0, 0)), img, shadow.filter(ImageFilter.GaussianBlur(2.2)))
    ImageDraw.Draw(img).text((x, y), line, font=font, fill=(242, 247, 241))
    return np.ascontiguousarray(np.asarray(img)[:, :, ::-1])


# The part of the 1080p frame the banner's TV shows (16:9, around the subtitle), so the line
# can be read in a small picture.
ZOOM = (320, 360, 1600, 1080)


def swap_frames(size: tuple[int, int]) -> list[tuple[Image.Image, int]]:
    """English line, a short blend, the Arabic in its place: for every line, as on the TV."""
    from tarjim.vision import render
    from tarjim.vision.detect import detect

    style = render.Style(fixed_size=None)
    frames = []
    for gid, en, ar in translations():
        print(f"  {gid}: {en} -> {ar}")
        base = scene(gid)
        frame = with_english(base, en)
        block = detect(frame)
        if block is None:
            raise RuntimeError(f"the detector did not find: {en}")
        after = render.composite(frame, [render.make_fill(frame, block), render.make_text(frame, block, ar, style)])
        to_img = lambda bgr: Image.fromarray(np.ascontiguousarray(bgr[:, :, ::-1])).crop(ZOOM).resize(size, Image.LANCZOS)  # noqa: E731
        frames.append((to_img(frame), 1100))
        for k in (1, 2, 3):
            mix = (frame.astype(np.float32) * (1 - k / 4) + after.astype(np.float32) * (k / 4)).astype(np.uint8)
            frames.append((to_img(mix), 60))
        frames.append((to_img(after), 2300))
    return frames


def save_gif(path: Path, still: Image.Image, box: tuple[int, int], frames: list[tuple[Image.Image, int]],
             colors: int = 220) -> None:
    """Frames that change only inside `box` of a still picture: one palette for all, the still
    part never dithered, so each frame stores only what changed."""
    picks = [img for img, _ in frames[:: max(1, len(frames) // 8)]]
    sample = Image.new("RGB", (still.width + sum(i.width for i in picks), max([still.height] + [i.height for i in picks])))
    sample.paste(still, (0, 0))
    x = still.width
    for img in picks:  # every kind of frame gets its colours into the palette
        sample.paste(img, (x, 0))
        x += img.width
    pal = sample.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    still_p = still.quantize(palette=pal, dither=Image.Dither.NONE)
    out = []
    for img, _ in frames:
        f = still_p.copy()
        f.paste(img.quantize(palette=pal, dither=Image.Dither.FLOYDSTEINBERG), box)
        out.append(f)
    out[0].save(path, save_all=True, append_images=out[1:], duration=[d for _, d in frames], loop=0, optimize=False)
    print(f"{path.name:14s} {path.stat().st_size / 1024:6.0f} KB  {len(out)} frames")


FONT = (REPO / "fonts" / "NotoSansArabic-VF.ttf").as_uri()
ICON = (WEB / "icon.png").as_uri()
BANNER_CSS = f"""
@font-face {{ font-family: "UI"; src: url("{FONT}"); font-weight: 100 900; }}
html, body {{ margin: 0; overflow: hidden; background: #0b0b0d; }}
body {{ font-family: "UI"; color: #f4f4f5; position: relative; }}
.glow {{ position: absolute; inset: 0;
  background: radial-gradient(520px 360px at 78% 38%, rgba(255,255,255,.07), transparent 70%),
              radial-gradient(640px 420px at 26% 60%, rgba(214,58,38,.20), transparent 72%); }}
.text {{ position: absolute; text-align: right; }}
.brand {{ display: flex; align-items: center; gap: 20px; }}
.icon {{ width: 88px; height: 88px; border-radius: 22px; box-shadow: 0 10px 30px rgba(0,0,0,.5); }}
h1 {{ font-size: 80px; font-weight: 800; margin: 0; line-height: 1.05; }}
.tag {{ font-size: 26px; line-height: 1.6; color: #d4d4d8; margin: 22px 0 28px; font-weight: 500; }}
.chips {{ display: flex; flex-wrap: wrap; gap: 10px; }}
.chip {{ font-size: 19px; padding: 8px 18px; border-radius: 999px; background: rgba(255,255,255,.08);
  border: 1px solid rgba(255,255,255,.15); font-weight: 600; }}
"""


def hero() -> None:
    """The laptop README's banner: a TV on the left whose screen plays the lines."""
    W, H = 1200, 540
    sx, sy, sw, sh = 52, 78, 640, 360  # the TV's screen
    html = f"""<!doctype html><html dir="rtl" lang="ar"><head><meta charset="utf-8"><style>{BANNER_CSS}
html, body {{ width: {W}px; height: {H}px; }}
.tv {{ position: absolute; left: {sx - 14}px; top: {sy - 14}px; width: {sw + 28}px; height: {sh + 28}px; border-radius: 18px;
  background: #151517; box-shadow: 0 30px 80px rgba(0,0,0,.65), inset 0 0 0 2px #2b2b30; }}
.screen {{ position: absolute; left: {sx}px; top: {sy}px; width: {sw}px; height: {sh}px; background: #000; }}
.stand {{ position: absolute; left: {sx + sw // 2 - 50}px; top: {sy + sh + 14}px; width: 100px; height: 30px;
  background: linear-gradient(#1d1d20, #101012); clip-path: polygon(20% 0, 80% 0, 100% 100%, 0 100%); }}
.base {{ position: absolute; left: {sx + sw // 2 - 110}px; top: {sy + sh + 42}px; width: 220px; height: 9px; border-radius: 5px; background: #1d1d20; }}
.text {{ right: 54px; top: 92px; width: 420px; }}
</style></head><body><div class="glow"></div>
<div class="tv"></div><div class="screen"></div><div class="stand"></div><div class="base"></div>
<div class="text"><div class="brand"><img class="icon" src="{ICON}"><h1>ترجِم</h1></div>
<div class="tag">ترجمة عربية تطلع مكان الإنجليزي<br>وأنت تلعب PS5 على التلفزيون</div>
<div class="chips"><span class="chip">⚡ أقل من ربع ثانية</span><span class="chip">🔌 بدون إنترنت</span>
<span class="chip">🎮 ما يلمس اللعبة</span><span class="chip">📚 ٢٨ لعبة جاهزة</span></div></div>
</body></html>"""
    still = chrome_png(html, W, H)
    save_gif(MEDIA / "hero.gif", still, (sx, sy), swap_frames((sw, sh)))


def phone_frame(screen: Image.Image, w: int = 300, h: int = 520) -> Image.Image:
    """A phone around a screenshot (the screenshot scaled to the phone's screen)."""
    pad, radius = 12, 44
    body = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    d = ImageDraw.Draw(body)
    d.rounded_rectangle((0, 0, body.width - 1, body.height - 1), radius=radius, fill=(22, 22, 25, 255),
                        outline=(58, 58, 64, 255), width=2)
    shot = screen.resize((w, h), Image.LANCZOS)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius - pad, fill=255)
    body.paste(shot, (pad, pad), mask)
    d.rounded_rectangle((w // 2 + pad - 34, pad + 8, w // 2 + pad + 34, pad + 22), radius=7, fill=(10, 10, 12, 255))
    return body


# The laptop program's phone remote has a "second screen"; the phone app has the look settings instead.
REMOTE_SCREENS = ["m-home", "m-home-shelf", "m-home-live", "m-library", "m-screen"]
APP_SCREENS = ["m-home", "m-home-shelf", "m-home-live", "m-library", "m-look"]


def phone_shots(names: list[str]) -> list[Image.Image]:
    shots = []
    for n in names:
        img = Image.open(OUT / f"app-{n}.png").convert("RGB")
        shots.append(img.crop((0, 0, img.width, min(img.height, int(img.width * 520 / 300)))))
    return shots


def phone_gif(target: Path, names: list[str]) -> None:
    """The pages at phone size, in a phone, on the app's own dark background."""
    frames = [phone_frame(s) for s in phone_shots(names)]
    W, H = frames[0].width + 80, frames[0].height + 60
    still = Image.new("RGB", (W, H), (11, 11, 13))
    out = []
    for f in frames:
        img = still.copy()
        img.paste(f, (40, 30), f)
        out.append((img, 2200))
    save_gif(target, still, (0, 0), out, colors=200)


def phone_hero(target: Path) -> None:
    """The phone README's banner: a phone on the left that goes through the app's screens."""
    W, H = 1200, 640
    px, py = 70, 44
    html = f"""<!doctype html><html dir="rtl" lang="ar"><head><meta charset="utf-8"><style>{BANNER_CSS}
html, body {{ width: {W}px; height: {H}px; }}
.text {{ right: 60px; top: 150px; width: 560px; }}
</style></head><body><div class="glow"></div>
<div class="text"><div class="brand"><img class="icon" src="{ICON}"><h1>ترجِم للجوال</h1></div>
<div class="tag">الجوال لحاله يترجم ألعاب الـPS5 ويرسم العربي<br>على التلفزيون. بدون لابتوب وبدون إنترنت.</div>
<div class="chips"><span class="chip">📱 بدون لابتوب</span><span class="chip">🔌 بدون إنترنت</span>
<span class="chip">📺 العربي على التلفزيون</span><span class="chip">📚 ٢٨ لعبة جاهزة</span></div></div>
</body></html>"""
    still = chrome_png(html, W, H)
    frames = []
    for s in phone_shots(APP_SCREENS):
        f = phone_frame(s)
        img = still.copy()
        img.paste(f, (px, py), f)
        frames.append((img.crop((px, py, px + f.width, py + f.height)), 2200))
    first = still.copy()
    first.paste(frames[0][0], (px, py))
    save_gif(target, first, (px, py), frames, colors=220)


def library(target: Path) -> None:
    """The covers of the library's games, in its own order."""
    packs = sorted((json.loads(p.read_text(encoding="utf-8")) for p in (REPO / "packs").glob("*.json")),
                   key=lambda p: p.get("order", 999))
    cols, cw, ch, gap = 7, 150, 225, 12
    rows = (len(packs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cw + (cols + 1) * gap, rows * ch + (rows + 1) * gap), (11, 11, 13))
    for i, p in enumerate(packs):
        cover = Image.open(WEB / "art" / f"{p['id']}-cover.webp").convert("RGB").resize((cw, ch), Image.LANCZOS)
        mask = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, cw - 1, ch - 1), radius=12, fill=255)
        r, c = divmod(i, cols)
        sheet.paste(cover, (gap + c * (cw + gap), gap + r * (ch + gap)), mask)
    sheet.save(target, quality=86, optimize=True)
    print(f"{target.name:14s} {target.stat().st_size / 1024:6.0f} KB  {len(packs)} games")


def tour() -> None:
    """The app's screens one after another."""
    names = ["home", "home-shelf", "home-live", "library", "look"]
    frames = []
    for n in names:
        img = Image.open(OUT / f"app-{n}.png").convert("RGB")
        img = img.crop((0, 0, img.width, min(img.height, int(img.width * 0.625))))
        frames.append((img.resize((960, 600), Image.LANCZOS), 2400))
    save_gif(MEDIA / "tour.gif", frames[0][0], (0, 0), frames, colors=230)


def copies() -> None:
    wanted = {"app-home.png": "home.png", "app-home-shelf.png": "home-shelf.png", "app-home-live.png": "home-live.png",
              "app-look.png": "look.png", "app-m-home.png": "phone-home.png",
              "app-m-home-shelf.png": "phone-shelf.png", "app-m-screen.png": "phone-screen.png"}
    for src, dst in wanted.items():
        img = Image.open(OUT / src).convert("RGB")
        if dst == "look.png":
            img = img.crop((0, 0, img.width, min(img.height, 1000)))
        img.save(MEDIA / dst, optimize=True)


if __name__ == "__main__":
    MEDIA.mkdir(parents=True, exist_ok=True)
    phone_repo = next((Path(a.split("=", 1)[1]) for a in sys.argv if a.startswith("--phone-repo=")), None)
    copies()
    tour()
    library(MEDIA / "library.jpg")
    phone_gif(MEDIA / "phone.gif", REMOTE_SCREENS)
    hero()
    if phone_repo:
        pm = phone_repo / "docs" / "media"
        pm.mkdir(parents=True, exist_ok=True)
        phone_hero(pm / "hero.gif")
        phone_gif(pm / "phone.gif", APP_SCREENS)
        library(pm / "library.jpg")
        for n in ("phone-home.png", "phone-shelf.png"):
            (pm / n).write_bytes((MEDIA / n).read_bytes())
        Image.open(OUT / "app-m-library.png").convert("RGB").save(pm / "phone-library.png", optimize=True)
