from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from tarjim.vision import arabic, render
from tarjim.vision.detect import detect, mask_iou
from tarjim.vision.tracker import Event, SubtitleTracker

from . import synth

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
GOLDEN = Path(__file__).parent / "golden"


@pytest.fixture(scope="module")
def samples():
    return synth.make_samples(n_text=72, n_empty=72)


def _iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def load_sample(name: str) -> np.ndarray:
    img = Image.open(SAMPLES / name).convert("RGB").resize((1920, 1080), Image.LANCZOS)
    return np.ascontiguousarray(np.asarray(img)[:, :, ::-1])


# -- detection ---------------------------------------------------------------


def test_detection_recall_and_false_positives(samples):
    text = [s for s in samples if s.text]
    empty = [s for s in samples if not s.text]
    hits = 0
    misses = []
    for s in text:
        b = detect(s.frame)
        if b is not None and _iou((b.x0, b.y0, b.x1, b.y1), s.bbox) >= 0.5 and len(b.lines) == len(s.lines):
            hits += 1
        else:
            misses.append((s.style, s.text[:30], None if b is None else (b.x0, b.y0, b.x1, b.y1), s.bbox))
    false_pos = sum(1 for s in empty if detect(s.frame) is not None)
    assert hits / len(text) >= 0.97, misses
    assert false_pos / len(empty) <= 0.01, false_pos


def test_user_samples_are_detected():
    b = detect(load_sample("uncharted-two-lines.webp"))
    assert b is not None and len(b.lines) == 2
    assert abs(b.lines[0].x0 - 588) <= 20 and abs(b.lines[1].x1 - 1331) <= 20
    b = detect(load_sample("rdr2-boxed-micah.webp"))
    assert b is not None and len(b.lines) == 1


def test_typewriter_triggers_once_after_last_character():
    line = "The bridge is out. We go around."
    frames = synth.typewriter_frames(line, hold=14)
    tracker = SubtitleTracker()
    events = []
    for i, frame in enumerate(frames):
        events.append(tracker.update(detect(frame), i * 33.3))
    new_at = [i for i, e in enumerate(events) if e is Event.NEW]
    assert len(new_at) == 1
    assert new_at[0] >= len(line) - 1  # not before the last character was typed
    assert Event.GONE not in events


def test_tracker_shows_refreshes_and_clears():
    s = synth.make_samples(2, 1, seed=11)
    with_text, other_text, empty = s[0].frame, s[1].frame, s[2].frame
    tracker = SubtitleTracker()
    seq = [empty] * 3 + [with_text] * 10 + [empty] * 4 + [other_text] * 10
    events = [tracker.update(detect(f), i * 33.3) for i, f in enumerate(seq)]
    assert events.count(Event.NEW) == 2
    assert events.count(Event.GONE) == 1
    first_new = events.index(Event.NEW)
    assert 3 + 4 <= first_new <= 3 + 7  # after the 150 ms settle time at 30 fps
    assert all(e is Event.REFRESH for e in events[first_new + 1 : 13])
    gone = events.index(Event.GONE)
    assert 13 <= gone <= 14  # within two frames of the text leaving


def test_rejected_block_is_not_retried_every_frame():
    s = synth.make_samples(1, 0, seed=5)[0]
    tracker = SubtitleTracker()
    news = 0
    for i in range(30):
        if tracker.update(detect(s.frame), i * 33.3) is Event.NEW:
            news += 1
            tracker.reject()
    assert news == 1


# -- erase ---------------------------------------------------------------------


def test_erase_leaves_no_detectable_text(samples):
    text = [s for s in samples if s.text and s.style != "boxed"]
    clean = 0
    for s in text:
        b = detect(s.frame)
        if b is None:
            continue
        erased = render.composite(s.frame, [render.make_fill(s.frame, b)])
        after = detect(erased)
        if after is None or mask_iou(after, b) < 0.05:
            clean += 1
    assert clean / len(text) >= 0.99


def test_fill_is_transparent_outside_the_strokes_and_zeroed():
    s = synth.make_samples(1, 0, seed=2)[0]
    b = detect(s.frame)
    fill = render.make_fill(s.frame, b)
    a = fill.bgra[:, :, 3]
    assert (a == 0).mean() > 0.4
    assert not fill.bgra[a == 0].any()  # no colour data under transparent pixels
    assert fill.png()[:8] == b"\x89PNG\r\n\x1a\n"


# -- Arabic rendering --------------------------------------------------------------

GOLDEN_CASES = {
    "joined": "السلام عليكم ورحمة الله",
    "lam-alef": "لا إله إلا الله، الأمل والآلام",
    "tanween": "شكراً جزيلاً، أهلاً وسهلاً، كتابٌ جديدٍ",
    "digits": "وصلنا في 1899 ومعنا 12 رجلاً.",
    "mixed": "ذهب Arthur إلى Valentine أمس.",
    "punct": "هل سمعت ذلك؟ شيء ما تحرّك!",
}


def _render_case(text: str) -> np.ndarray:
    shaped = arabic.shape_line(text, 48, "harmattan")
    alpha, _, _ = arabic.rasterize(shaped, 48)
    return alpha


def _ssim(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a.astype(np.float64), b.astype(np.float64)
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mu_a, mu_b = cv2.GaussianBlur(a, (0, 0), 1.5), cv2.GaussianBlur(b, (0, 0), 1.5)
    va = cv2.GaussianBlur(a * a, (0, 0), 1.5) - mu_a**2
    vb = cv2.GaussianBlur(b * b, (0, 0), 1.5) - mu_b**2
    cov = cv2.GaussianBlur(a * b, (0, 0), 1.5) - mu_a * mu_b
    s = ((2 * mu_a * mu_b + c1) * (2 * cov + c2)) / ((mu_a**2 + mu_b**2 + c1) * (va + vb + c2))
    return float(s.mean())


@pytest.mark.parametrize("name", list(GOLDEN_CASES))
def test_arabic_golden_images(name):
    img = _render_case(GOLDEN_CASES[name])
    path = GOLDEN / f"{name}.png"
    if not path.exists():
        GOLDEN.mkdir(exist_ok=True)
        cv2.imwrite(str(path), img)
        pytest.fail(f"golden image created at {path}; inspect it, then run again")
    gold = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    assert gold.shape == img.shape
    assert _ssim(gold, img) >= 0.98


def test_shaping_joins_letters_and_has_no_missing_glyphs():
    for text in GOLDEN_CASES.values():
        shaped = arabic.shape_line(text, 48)
        assert shaped.missing == 0, text
        assert shaped.width > 0
    # Joined Arabic uses contextual forms: far fewer distinct "isolated" advances than letters.
    joined = arabic.shape_line("بببب", 48)
    isolated = arabic.shape_line("ب ب ب ب", 48)
    assert joined.width < isolated.width
    # lam + alef becomes one ligature glyph.
    assert len(arabic.shape_line("لا", 48).glyphs) == 1


def test_bidi_keeps_latin_names_and_numbers_in_reading_order():
    runs = arabic.bidi_runs("ذهب Arthur Morgan إلى Valentine في 1899.")
    assert ("L", "Arthur Morgan") in runs  # the space inside a Latin name stays with it
    assert ("L", "Valentine") in runs and ("L", "1899") in runs
    assert runs[-1] == ("R", ".")  # final full stop belongs to the Arabic sentence
    assert arabic.bidi_runs("الساعة 10:30 تماماً")[1] == ("L", "10:30")
    # Visual order: the first logical word ends up at the right edge.
    shaped = arabic.shape_line("أ Arthur", 48)
    latin_x = [g.x for g in shaped.glyphs if g.font is not None][:6]
    assert latin_x == sorted(latin_x)


def test_layout_stays_inside_block_with_integer_rects():
    frame = load_sample("uncharted-two-lines.webp")
    b = detect(frame)
    texts = [
        "قصير.",
        "الآن عليك أن تبقى هنا معي طوال عطلة نهاية الأسبوع بدلاً من الذهاب في الرحلة مع الجميع.",
        "هذه جملة طويلة جداً جداً كتبناها لنتأكد أن النص العربي ينقسم إلى أسطر ولا يخرج أبداً عن حدود مكان الترجمة الأصلية مهما طال الكلام.",
    ]
    max_w = max(l.x1 - l.x0 for l in b.lines)
    for text in texts:
        lay = render.layout_text(text, b, render.Style())
        assert lay.width <= max_w + 1, text
        assert lay.baselines[-1] == render.latin_metrics(b)[1][-1]  # bottom baseline stays fixed
        layer = render.make_text(frame, b, text)
        for v in (layer.x, layer.y, layer.w, layer.h):
            assert isinstance(v, int)
        assert layer.x >= 0 and layer.y >= 0 and layer.x + layer.w <= 1920 and layer.y + layer.h <= 1080
    lay = render.layout_text(texts[1], b, render.Style())
    assert len(lay.lines) == 2 and lay.size == 47  # the value validated on this sample in the brief


def test_line_split_by_a_bright_patch_is_detected_whole():
    """White letters over a bright part of the scene vanish from the stroke
    mask; the pieces on both sides must still come back as one line."""
    rng = np.random.default_rng(9)
    bg = synth.background(rng, "dark")
    line = "Still need more supplies, my friend. You should try your luck again."
    plain, bbox = synth.draw_subtitle(bg.copy(), [line], "shadow", 40, 1000)
    x0, y0, x1, y1 = bbox
    mid = (x0 + x1) // 2
    bg[y0 - 30 : y1 + 30, mid - 45 : mid + 45] = 235  # e.g. snow or a lamp behind four letters
    frame, _ = synth.draw_subtitle(bg, [line], "shadow", 40, 1000)
    b = detect(frame)
    assert b is not None and len(b.lines) == 1
    assert abs(b.lines[0].x0 - x0) <= 12 and abs(b.lines[0].x1 - x1) <= 20  # the final full stop is not a glyph


def test_user_region_limits_where_text_is_found():
    """Text outside the region the user drew (a menu, for example) is ignored."""
    from tarjim import settings

    rng = np.random.default_rng(3)
    bg = synth.background(rng, "dark")
    frame, bbox = synth.draw_subtitle(bg, ["Keep your voice down and stay close."], "shadow", 40, 1000)
    assert detect(frame) is not None
    left_third = settings.detect_params({"region": {"left": 0.0, "top": 0.7, "right": 0.33, "bottom": 1.0}})
    assert detect(frame, left_third) is None  # the line is in the middle of the screen
    top_half = settings.detect_params({"region": {"left": 0.05, "top": 0.05, "right": 0.95, "bottom": 0.5}})
    assert detect(frame, top_half) is None
    whole = settings.detect_params({"region": {"left": 0.0, "top": 0.5, "right": 1.0, "bottom": 1.0}})
    b = detect(frame, whole)
    assert b is not None and abs(b.lines[0].x0 - bbox[0]) <= 12  # coordinates stay in frame pixels
    # Subtitles at the top of the screen can be found once the region says so.
    top_frame, top_box = synth.draw_subtitle(synth.background(rng, "dark"), ["Nobody comes back from the northern road."], "shadow", 40, 160)
    assert detect(top_frame) is None
    found = detect(top_frame, top_half)
    assert found is not None and abs(found.lines[0].y0 - top_box[1]) <= 14
    # Nonsense input falls back to the default area instead of breaking detection.
    assert settings.region({"region": {"left": "x"}}) == settings.DEFAULT_REGION
    r = settings.region({"region": {"left": 0.5, "top": 0.5, "right": 0.5, "bottom": 0.5}})
    assert r["right"] - r["left"] >= 0.099 and r["bottom"] - r["top"] >= 0.079
