"""Download the official art of the library's games: python launcher/fetch_art.py [--cache DIR]

Both apps show each game with its own pictures: a wide background, a tall one for phones,
the box cover and the logo. They come from the publishers' own store art on Steam's
image server (by Steam app id), and for GTA VI (not on Steam) from Rockstar's own page.
The art belongs to the publishers; it is only shown to the player to pick a game.

Writes tarjim/app/web/art/<id>-{bg,tall,cover,logo}.webp and tarjim/app/web/art.js
(where each picture's subject is, which games have a logo, and the titles to match a game
the user made himself). Then run launcher/sync_phone_web.py for the phone app.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tempfile
import urllib.request
from pathlib import Path

from PIL import Image

LAPTOP = Path(__file__).resolve().parents[1]
REPO = LAPTOP.parent
WEB = LAPTOP / "tarjim" / "app" / "web"
OUT = WEB / "art"
STEAM = "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{app}/{file}"
ROCKSTAR_VI = "https://www.rockstargames.com/VI"

# pack id -> (Steam app id, where the subject is across the wide picture, 0..100)
GAMES = {
    "bg3": (1086940, 30), "bully": (12200, 70), "ff7r": (1462040, 55), "gta-sa": (12120, 62),
    "gta4": (12210, 74), "gta5": (271590, 72), "kcd2": (1771300, 62), "la-noire": (110800, 72),
    "lad-gaiden": (2375550, 16), "lad-pirate": (3061810, 10), "lad7": (1235140, 72), "lad8": (2072450, 22),
    "mafia-toc": (1941540, 66), "max-payne-3": (204100, 70), "p5r": (1687950, 70), "rdr1": (2668510, 52),
    "rdr2": (1174180, 72), "sh2r": (2124490, 50), "tlou1": (1888930, 50), "tlou2": (2531310, 52),
    "yakuza-kiwami": (834530, 50), "yakuza-kiwami2": (927380, 76), "yakuza0": (638970, 82),
    "yakuza3": (1088710, 26), "yakuza4": (1105500, 64), "yakuza5": (1105510, 55), "yakuza6": (1388590, 55),
}
GTA6_FOCUS = 50


def fetch(url: str, cache: Path) -> bytes:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", url.split("://", 1)[1])[-120:]
    path = cache / name
    if path.exists():
        return path.read_bytes()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (tarjim art fetch)"})
    with urllib.request.urlopen(req, timeout=40) as res:
        data = res.read()
    path.write_bytes(data)
    return data


def image(data: bytes) -> Image.Image:
    im = Image.open(io.BytesIO(data))
    im.load()
    return im


def save(im: Image.Image, name: str, quality: int = 74) -> int:
    path = OUT / name
    im.save(path, "WEBP", quality=quality, method=6)
    return path.stat().st_size


def tall_slice(hero: Image.Image, focus: float) -> Image.Image:
    """A 1:2 portrait slice of the wide picture, around the subject, for phone screens."""
    w, h = hero.size
    sw = h // 2
    x = int(round(w * focus / 100 - sw / 2))
    x = max(0, min(w - sw, x))
    return hero.crop((x, 0, x + sw, h))


def logo(im: Image.Image) -> Image.Image:
    rgba = im.convert("RGBA")
    box = rgba.getchannel("A").getbbox()
    return rgba.crop(box) if box else rgba


def steam_game(gid: str, app: int, focus: int, cache: Path) -> dict:
    hero = image(fetch(STEAM.format(app=app, file="library_hero_2x.jpg"), cache)).convert("RGB")
    cover = image(fetch(STEAM.format(app=app, file="library_600x900.jpg"), cache)).convert("RGB")
    sizes = [
        save(hero.resize((2560, round(hero.height * 2560 / hero.width)), Image.LANCZOS), f"{gid}-bg.webp"),
        save(tall_slice(hero, focus), f"{gid}-tall.webp"),
        save(cover.resize((600, 900), Image.LANCZOS), f"{gid}-cover.webp", 80),
    ]
    has_logo = True
    try:
        mark = logo(image(fetch(STEAM.format(app=app, file="logo.png"), cache)))
        sizes.append(save(mark, f"{gid}-logo.webp", 88))
    except Exception:
        has_logo = False
    return {"x": focus, "logo": has_logo, "bytes": sum(sizes)}


def gta6(cache: Path) -> dict:
    """GTA VI is not on Steam: the cover art Rockstar puts on its own page (the page's share picture)."""
    page = fetch(ROCKSTAR_VI, cache).decode("utf-8", "replace")
    m = re.search(r'property="og:image" content="([^"]+)"', page) or re.search(r'"og:image" content="([^"]+)"', page)
    if not m:
        raise RuntimeError("no share picture on Rockstar's GTA VI page")
    art = image(fetch(m.group(1).replace("&amp;", "&"), cache)).convert("RGB")
    w, h = art.size
    cw = round(h * 2 / 3)  # the cover: a 2:3 cut around the logo in the middle
    x = (w - cw) // 2
    sizes = [
        save(art, "gta6-bg.webp", 80),
        save(tall_slice(art, GTA6_FOCUS), "gta6-tall.webp", 80),
        save(art.crop((x, 0, x + cw, h)).resize((600, 900), Image.LANCZOS), "gta6-cover.webp", 80),
    ]
    return {"x": GTA6_FOCUS, "logo": False, "bytes": sum(sizes)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", help="keep the downloads here (default: a new temporary folder)")
    args = ap.parse_args()
    cache = Path(args.cache) if args.cache else Path(tempfile.mkdtemp(prefix="tarjim-art-"))
    cache.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(exist_ok=True)

    titles, arabic = {}, {}
    for p in sorted((REPO / "packs").glob("*.json")):
        pack = json.loads(p.read_text(encoding="utf-8"))
        titles[pack["id"]] = pack.get("title", pack["id"])
        arabic[pack["id"]] = pack.get("title_ar", "")

    meta, total = {}, 0
    for gid, (app, focus) in GAMES.items():
        info = steam_game(gid, app, focus, cache)
        total += info.pop("bytes")
        meta[gid] = {**info, "t": titles.get(gid, gid), "ar": arabic.get(gid, "")}
        print(f"{gid:16} ok{'' if info['logo'] else ' (no logo)'}")
    try:
        info = gta6(cache)
        total += info.pop("bytes")
        meta["gta6"] = {**info, "t": titles.get("gta6", "Grand Theft Auto VI"), "ar": arabic.get("gta6", "")}
        print(f"{'gta6':16} ok (Rockstar)")
    except Exception as exc:
        print(f"gta6             skipped: {exc}")

    body = json.dumps(meta, ensure_ascii=False, separators=(",", ":"))
    (WEB / "art.js").write_text(
        "// Written by launcher/fetch_art.py: which games have their own pictures in art/,\n"
        "// where the subject of the wide picture is (x, percent), whether there is a logo, and the\n"
        "// English and Arabic titles (to recognise a game the user added by hand).\n"
        f"window.ART = {body};\n", encoding="utf-8", newline="\n")
    print(f"{len(meta)} games, {total / 1e6:.1f} MB in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
