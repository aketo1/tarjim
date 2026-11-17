"""The games' own pictures: every library game has them, they are real pictures of the right shape,
and the phone app's copy of the page takes every file the page loads."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

from PIL import Image

LAPTOP = Path(__file__).resolve().parents[1]
REPO = LAPTOP.parent
WEB = LAPTOP / "tarjim" / "app" / "web"


def art_list() -> dict:
    text = (WEB / "art.js").read_text(encoding="utf-8")
    m = re.search(r"window\.ART = (\{.*\});", text, re.S)
    assert m, "art.js is not in the shape launcher/fetch_art.py writes"
    return json.loads(m.group(1))


def test_every_library_game_has_its_pictures():
    art = art_list()
    for p in sorted((REPO / "packs").glob("*.json")):
        gid = json.loads(p.read_text(encoding="utf-8"))["id"]
        assert gid in art, f"{gid}: run launcher/fetch_art.py"
        assert 0 <= art[gid]["x"] <= 100
        for kind in ("bg", "tall", "cover"):
            assert (WEB / "art" / f"{gid}-{kind}.webp").is_file(), (gid, kind)
        assert (WEB / "art" / f"{gid}-logo.webp").is_file() == art[gid]["logo"], gid


def test_pictures_are_real_and_shaped_for_their_place():
    for f in sorted((WEB / "art").glob("*.webp")):
        with Image.open(f) as im:
            assert im.format == "WEBP", f.name
            w, h = im.size
        kind = f.stem.rsplit("-", 1)[1]
        if kind == "cover":
            assert (w, h) == (600, 900), f.name  # a box cover, 2:3
        elif kind == "tall":
            assert abs(w * 2 - h) <= 2, f.name  # a phone's slice of the wide picture, 1:2
        elif kind == "bg":
            assert w > h * 1.5, f.name  # wide, for a computer's window
        else:
            assert kind == "logo", f.name


def test_phone_copy_takes_every_file_the_page_loads():
    spec = importlib.util.spec_from_file_location("sync_phone_web", LAPTOP / "launcher" / "sync_phone_web.py")
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    names = sync.wanted()
    page = (WEB / "index.html").read_text(encoding="utf-8")
    loaded = re.findall(r'<script src="([^"]+)"', page) + re.findall(r'<link rel="stylesheet" href="([^"]+)"', page)
    assert loaded and all(n in names for n in loaded), loaded
    assert "glass.js" not in names and not (WEB / "glass.js").exists()
    assert sorted(n for n in names if n.startswith("art/")) == sorted(f"art/{f.name}" for f in (WEB / "art").iterdir())
