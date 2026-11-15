import time
from pathlib import Path

import numpy as np
import pytest

from tarjim.faketv import FakeTv
from tarjim.pipeline import Pipeline
from tarjim.translate import Cache, CachedTranslator, apply_glossary, normalize_arabic, normalize_english
from tarjim.tvlink import TvLink
from tarjim.vision.detect import detect
from tarjim.vision.ocr import OcrEngine, join_lines, looks_like_subtitle, split_speaker
from tarjim.vision.tracker import Event

from . import synth
from .test_vision import SAMPLES, load_sample


@pytest.fixture(scope="module")
def ocr():
    return OcrEngine()


def _cer(ref: str, hyp: str) -> tuple[int, int]:
    """Levenshtein distance and reference length."""
    prev = list(range(len(hyp) + 1))
    for i, rc in enumerate(ref, 1):
        cur = [i]
        for j, hc in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc)))
        prev = cur
    return prev[-1], len(ref)


# -- OCR -----------------------------------------------------------------------


def test_ocr_character_error_rate_on_synthetic_set(ocr):
    errors = total = 0
    worst = []
    for s in synth.make_samples(n_text=36, n_empty=0, seed=21):
        b = detect(s.frame)
        assert b is not None, s.text
        got = ocr.read(s.frame, b)
        e, n = _cer(s.text, got.text)
        errors += e
        total += n
        if e:
            worst.append((s.style, s.text, got.text))
    assert errors / total <= 0.02, worst


@pytest.mark.parametrize("image", ["uncharted-two-lines.webp", "rdr2-boxed-micah.webp"])
def test_ocr_reads_user_samples_exactly(ocr, image):
    expected = (SAMPLES / (Path(image).stem + ".txt")).read_text(encoding="utf-8-sig").strip()
    frame = load_sample(image)
    got = ocr.read(frame, detect(frame))
    assert got.ok and got.text == expected


def test_text_helpers():
    assert join_lines(["Now you have to stay", "with everyone else."]) == "Now you have to stay with everyone else."
    assert join_lines(["an unbeliev-", "able story"]) == "an unbelievable story"
    assert split_speaker("MARIA: We go around.") == ("MARIA", "We go around.")
    assert split_speaker("We go around: now.") == (None, "We go around: now.")
    assert looks_like_subtitle("Keep your voice down.")
    assert not looks_like_subtitle("12:45") and not looks_like_subtitle("警告 危険")
    assert not looks_like_subtitle("PS5") and not looks_like_subtitle("OLD TOWN")
    assert looks_like_subtitle("No.") and looks_like_subtitle("RUN!") and looks_like_subtitle("We have 12 men.")


# -- translation plumbing (no model) ------------------------------------------------


class FakeEngine:
    name = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def translate(self, text, context=None):
        self.calls += 1
        return '  "ترجمة: ' + text[:10] + ' , نعم?"  '


def test_cache_hit_is_fast_and_skips_the_engine():
    engine = FakeEngine()
    tr = CachedTranslator(engine, Cache(":memory:"), profile="p")
    ar1, hit1, _ = tr.translate("Keep  your voice down.")
    ar2, hit2, ms2 = tr.translate("Keep your voice down.")  # same after normalisation
    assert (hit1, hit2) == (False, True) and ar1 == ar2 and engine.calls == 1
    assert ms2 < 2.0
    other = CachedTranslator(engine, tr.cache, profile="other-game")
    assert other.translate("Keep your voice down.")[1] is False  # the profile is part of the key


def test_arabic_and_english_normalisation():
    assert normalize_english("  It’s   “fine”  ") == 'It\'s "fine"'
    assert normalize_arabic('"هل سمعت ذلك ?"') == "هل سمعت ذلك؟"
    assert normalize_arabic("نعم , لا ;") == "نعم، لا؛"
    assert normalize_arabic("انتظر......") == "انتظر..."
    assert normalize_arabic("بَنَى أَبِي هَذَا المَنْزِلَ") == "بنى أبي هذا المنزل"
    assert normalize_arabic("شكراً جزيلاً، تحرّك") == "شكراً جزيلاً، تحرّك"  # tanween and shadda stay
    assert normalize_arabic("Arthur, come here") == "Arthur, come here"  # Latin text keeps its commas
    assert apply_glossary("ذهب Arthur إلى البلدة", "Arthur went to town", {"Arthur": "آرثر"}) == "ذهب آرثر إلى البلدة"


# -- end to end on FakeTv -------------------------------------------------------------


def _wait(cond, timeout=1.5):
    end = time.monotonic() + timeout
    while time.monotonic() < end and not cond():
        time.sleep(0.01)
    return cond()


def test_end_to_end_overlays_appear_and_clear(ocr):
    s = synth.make_samples(2, 1, seed=11)
    line_a, line_b, empty = s[0], s[1], s[2]

    class DictEngine:
        name = "dict"

        def translate(self, text, context=None):
            return {line_a.text: "السطر الأول.", line_b.text: "السطر الثاني."}[text]

    with FakeTv() as tv, TvLink(tv.host, tv.port) as link:
        link.connect()
        pipe = Pipeline(link, CachedTranslator(DictEngine(), Cache(":memory:")), ocr)
        t = 100.0
        seen = []

        def feed(frame, n):
            nonlocal t
            for _ in range(n):
                seen.append(pipe.process(frame, t))
                t += 1 / 30

        feed(empty.frame, 4)
        assert tv.layer_ids() == []
        feed(line_a.frame, 10)
        assert _wait(lambda: tv.layer_ids() == ["fill", "text"])
        assert seen.count(Event.NEW) == 1
        shown = np.asarray(tv.composite().convert("RGB"))
        x0, y0, x1, y1 = line_a.bbox
        assert shown[y0:y1, x0:x1].max() > 150  # Arabic pixels were drawn where the English is
        assert shown[: y0 - 80].max() == 0 and shown[:, : x0 - 150].max() == 0  # and nowhere far from it

        # The line leaves before it could be read: the Arabic stays on a dark
        # plate (no stroke fill: there is no English under it any more) ...
        feed(empty.frame, 4)
        assert _wait(lambda: tv.layer_ids() == ["plate", "text"])
        assert pipe.held == 1
        # ... and is cleared once its reading time is over.
        deadline = time.monotonic() + 4.0
        while tv.layer_ids() and time.monotonic() < deadline:
            feed(empty.frame, 1)
            time.sleep(0.03)
        assert tv.layer_ids() == []
        feed(line_b.frame, 10)
        assert _wait(lambda: tv.layer_ids() == ["fill", "text"])
        assert pipe.lines_shown == 2

        # A new line arriving while the previous one is held replaces it at once.
        feed(empty.frame, 4)
        assert _wait(lambda: "plate" in tv.layer_ids())
        feed(line_a.frame, 10)  # a repeated line: comes from the cache
        assert _wait(lambda: tv.layer_ids() == ["fill", "text"])
        assert pipe.times.mt_cached and max(pipe.times.mt_cached) < 2.0
        pipe.close()
        assert _wait(lambda: tv.layer_ids() == [])


def test_stalled_pipeline_never_leaves_stale_arabic(ocr):
    s = synth.make_samples(1, 0, seed=4)[0]

    class OneEngine:
        name = "one"

        def translate(self, text, context=None):
            return "سطر."

    with FakeTv() as tv:
        link = TvLink(tv.host, tv.port, auto_reconnect=False)
        link.connect()
        pipe = Pipeline(link, CachedTranslator(OneEngine(), Cache(":memory:")), ocr)
        for i in range(10):
            pipe.process(s.frame, 50.0 + i / 30)
        assert _wait(lambda: tv.layer_ids() == ["fill", "text"])
        # The pipeline freezes: no more frames, no refresh. Layers expire by TTL (0.7 s) on their own.
        t0 = time.monotonic()
        assert _wait(lambda: tv.layer_ids() == [], timeout=1.2)
        assert time.monotonic() - t0 <= 1.0
        link.close()


def test_reading_time_scales_with_length():
    from tarjim.pipeline import reading_time_ms

    assert reading_time_ms("نعم.") == 1600.0
    assert 3000 < reading_time_ms("س" * 50) < 5000
    assert reading_time_ms("س" * 300) == 6000.0


def test_gemini_engine_falls_back_and_backs_off_without_network(monkeypatch):
    """No real request is made: the client is replaced by one that fails."""
    from tarjim import translate as T

    monkeypatch.setattr(T, "load_env_key", lambda name="GEMINI_API_KEY": "test-key")

    class Local:
        name = "local"

        def __init__(self):
            self.calls = 0

        def translate(self, text, context=None):
            self.calls += 1
            return "محلي"

    class Boom:
        def __init__(self, message):
            self.message = message
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            assert kwargs["store"] is False and kwargs["timeout"] == 1.2
            assert kwargs["generation_config"]["thinking_level"] == "minimal"
            raise RuntimeError(self.message)

    local = Local()
    g = T.GeminiTranslator(fallback=local, glossary={"Morgan": "مورغان"})
    boom = Boom("429 RESOURCE_EXHAUSTED")
    g._client = type("C", (), {"interactions": boom})()
    assert g.translate("Hello, Mr. Morgan.") == "محلي" and g.last_used == "local"
    assert g.translate("Again.") == "محلي"
    assert boom.calls == 1  # after a quota error Gemini is not asked again for a while
    assert local.calls == 2 and g.fallbacks == 2

    text = g._input("Hello, Mr. Morgan.", [("a", "x"), ("b", "y"), ("c", "z")])
    assert "Morgan=مورغان" in text and "Before: b / c" in text and text.endswith("Line: Hello, Mr. Morgan.")

    # A fallback answer is cached under the local engine's name, so Gemini is tried again later.
    cache = Cache(":memory:")
    tr = CachedTranslator(g, cache)
    tr.translate("Keep it coming.")
    assert cache.get("default", "Keep it coming.", "gemini", "msa") is None
    assert cache.get("default", "Keep it coming.", "local", "msa") == "محلي"
