"""Screen text (GTA VI): menus, prompts and phone messages on a screen drawn here, with words
written for these tests. Checks what is found, what is drawn where, and what is never touched
(icons and buttons), end to end on the fake TV."""

import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from tarjim import gta6, screen_text
from tarjim.faketv import FakeTv
from tarjim.pipeline import Pipeline
from tarjim.translate import Cache, CachedTranslator
from tarjim.tvlink import TvLink
from tarjim.vision.ocr import OcrEngine
from tarjim.vision.screen import Zone, build_item, find_all

FONT = Path(__file__).resolve().parents[2] / "fonts" / "NotoSans-VF.ttf"
MENU = ["Settings", "Help", "Store", "Gallery"]  # rows of a pause menu; the first is selected
MESSAGE = ["Meet me at the old pier tonight.", "Bring the boat keys."]
SENDER = "Marla"


def _screen(menu=True, prompts=True, card=True) -> tuple[np.ndarray, dict]:
    """A 1080p screen: a dark menu panel with icons on the left, button prompts at the bottom
    right, a white message card above them. Returns the BGR frame and where things are."""
    img = Image.new("RGB", (1920, 1080))
    px = np.zeros((1080, 1920, 3), np.uint8)
    px[:, :, 0] = np.linspace(70, 150, 1920, dtype=np.uint8)[None, :]  # a calm, uneven backdrop
    px[:, :, 1] = np.linspace(90, 60, 1080, dtype=np.uint8)[:, None]
    px[:, :, 2] = 110
    img = Image.fromarray(px)
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(str(FONT), 30)
    fb = ImageFont.truetype(str(FONT), 28)
    fb.set_variation_by_axes([700])
    where: dict = {"icons": [], "buttons": []}
    if menu:
        d.rectangle([0, 0, 600, 1080], fill=(38, 36, 52))
        for k, word in enumerate(MENU):
            y = 240 + 72 * k
            if k == 0:  # the selected row: a white bar, dark letters
                d.rectangle([32, y - 16, 520, y + 42], fill=(246, 246, 246))
            ink = (40, 40, 48) if k == 0 else (236, 236, 240)
            d.rectangle([50, y + 2, 72, y + 24], outline=ink, width=3)  # the row's icon
            where["icons"].append((50, y + 2, 73, y + 25))
            d.text((92, y - 6), word, font=f, fill=ink)
    if prompts:
        for k, word in enumerate(["SELECT", "BACK"]):
            y = 1010
            x1 = 1650 + 150 * k
            w = d.textlength(word, font=fb)
            d.text((x1 - w, y - 4), word, font=fb, fill=(245, 245, 245))
            d.ellipse([x1 + 12, y, x1 + 40, y + 28], outline=(245, 245, 245), width=3)  # its button
            where["buttons"].append((x1 + 12, y, x1 + 41, y + 29))
    if card:
        d.rounded_rectangle([1460, 760, 1880, 930], radius=18, fill=(250, 250, 250))
        d.ellipse([1478, 776, 1508, 806], fill=(200, 120, 90))  # the sender's picture
        where["avatar"] = (1478, 776, 1509, 807)
        d.text((1524, 772), SENDER, font=fb, fill=(30, 30, 34))
        for k, line in enumerate(MESSAGE):
            d.text((1484, 828 + 36 * k), line, font=f, fill=(60, 60, 66))
    frame = np.ascontiguousarray(np.asarray(img)[:, :, ::-1])
    return frame, where


ZONES = tuple(Zone(*z) for z in gta6.ZONES)


def test_found_items_leave_icons_and_buttons_out():
    frame, where = _screen()
    cands = find_all(frame, ZONES)
    menu = [c for c in cands if c.zone == "left"]
    assert len(menu) == len(MENU)
    assert sum(c.dark for c in menu) == 1  # the selected row: dark letters on its white bar
    for c in menu:
        item = build_item(frame, c)
        # nothing of an icon is in the strokes the cover hides
        assert min(l.x0 for l in item.lines) >= 80
    cards = [c for c in cands if c.panel_bgr is not None]
    # (light gaps between a message's letters are found too; the reader drops what a message covers)
    prompts = [c for c in cands if c.zone == "prompts" and c.box[1] > 960]
    assert len(prompts) == 2
    for c, (bx0, _y0, _bx1, _y1) in zip(sorted(prompts, key=lambda c: c.box[0]), where["buttons"]):
        assert c.runs[0].x1 <= bx0  # the button after a prompt is not part of it
    head = [c for c in cards if c.head]
    body = [c for c in cards if not c.head and len(c.runs) == 2]
    assert len(head) == 1 and len(body) == 1
    assert head[0].runs[0].x0 >= where["avatar"][2]  # the sender's picture stays untouched


class Engine:
    name = "test"
    calls: list = []

    def translate(self, text, context=None):
        Engine.calls.append(text)
        return "قابلني عند الرصيف القديم الليلة. أحضر مفاتيح القارب."


@pytest.fixture(scope="module")
def ocr():
    return OcrEngine()


def _wait(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end and not cond():
        time.sleep(0.02)
    return cond()


def test_screen_text_end_to_end_on_the_fake_tv(ocr):
    frame, where = _screen()
    empty, _ = _screen(menu=False, prompts=False, card=False)
    Engine.calls = []
    tr = CachedTranslator(Engine(), Cache(":memory:"), profile="gta6", glossary={SENDER: "مارلا"})
    with FakeTv() as tv, TvLink(tv.host, tv.port) as link:
        link.connect()
        st = screen_text.ScreenText(link, tr, ocr, ZONES, game=gta6)
        t = 1000.0
        try:
            for _ in range(6):
                st.step(frame, now=t)
                t += 130
            assert _wait(lambda: len(tv.layer_ids()) >= 2)
            layers = tv.layers()
            assert all(l.win == "B" for l in layers.values())  # never in the subtitles' window
            shown = {tr_.english: tr_.arabic for tr_ in st._tracks if tr_.state == "shown"}
            assert shown.get("Settings") == "الإعدادات" and shown.get("BACK") == "رجوع"
            assert shown.get(SENDER) == "مارلا"
            # the message is read as one paragraph (both its lines), and drawn from the engine
            assert any("pier" in en and "keys" in en for en in shown), shown
            assert Engine.calls and all("Settings" not in c for c in Engine.calls)  # table words skip it
            after = np.asarray(tv.composite(Image.fromarray(frame[:, :, ::-1].copy())).convert("RGB"))[:, :, ::-1]
            # The Arabic changed the menu rows, the prompts and the message ...
            assert np.abs(after[230:300, 90:300].astype(int) - frame[230:300, 90:300]).max() > 60
            assert np.abs(after[825:900, 1484:1860].astype(int) - frame[825:900, 1484:1860]).max() > 60
            # ... and left every icon, button and the sender's picture exactly as they were.
            for x0, y0, x1, y1 in where["icons"] + where["buttons"] + [where["avatar"]]:
                assert np.abs(after[y0:y1, x0:x1].astype(int) - frame[y0:y1, x0:x1]).max() <= 8
            # When the screen goes, so does its Arabic.
            for _ in range(4):
                st.step(empty, now=t)
                t += 130
            assert _wait(lambda: tv.layer_ids() == [])
        finally:
            st.close()


def test_subtitles_clear_only_their_own_layers(ocr):
    frame, _ = _screen(prompts=False, card=False)
    tr = CachedTranslator(Engine(), Cache(":memory:"), profile="gta6")
    with FakeTv() as tv, TvLink(tv.host, tv.port) as link:
        link.connect()
        pipe = Pipeline(link, tr, ocr)
        st = screen_text.attach(pipe, tr, ocr)
        st.close()  # driven by hand here, without its thread
        st._stop = False
        t = 1000.0
        for _ in range(6):
            st.step(frame, now=t)
            t += 130
        assert _wait(lambda: any(i.startswith("ui") for i in tv.layer_ids()))
        pipe._text_up = True
        pipe._clear()  # a subtitle's time is up
        time.sleep(0.2)
        assert any(i.startswith("ui") for i in tv.layer_ids())
        # screen text leaves the subtitles' own reading alone: no filter on what they read
        assert not hasattr(pipe, "not_speech")
        pipe.close()
        assert _wait(lambda: tv.layer_ids() == [])
