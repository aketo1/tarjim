"""`tarjim bench latency`: measure every stage on this laptop and print the budget table."""

from __future__ import annotations

import time

import cv2
import numpy as np
from PIL import Image

from . import paths
from .say import info, ok, step, warn
from .translate import ENGINES, TranslateError, default_engine_name
from .vision import render
from .vision.detect import detect
from .vision.ocr import OcrEngine

BUDGETS = {"detect": 8.0, "ocr": 120.0, "mt": 250.0, "render": 20.0}
TEST_LINES = [
    "We should leave before the storm gets here.",
    "I never asked you to follow me.",
    "Keep your voice down and stay close.",
    "My father built this house with his own hands.",
    "There is no map for where we are going.",
    "Hold the lantern higher, I can't see a thing.",
    "She left a letter. It is addressed to you.",
    "Every winter the river freezes over and the whole valley goes silent.",
]


def _load_samples() -> list[np.ndarray]:
    frames = []
    for p in sorted((paths.REPO / "samples").glob("*.webp")) + sorted((paths.REPO / "samples").glob("*.png")):
        img = Image.open(p).convert("RGB").resize((1920, 1080), Image.LANCZOS)
        frames.append(np.ascontiguousarray(np.asarray(img)[:, :, ::-1]))
    return frames


def _stats(values: list[float]) -> tuple[float, float]:
    a = np.array(values)
    return float(np.percentile(a, 50)), float(np.percentile(a, 90))


def latency(engine: str | None) -> int:
    frames = _load_samples()
    if not frames:
        warn("حط لقطة حوار وحدة على الأقل في مجلد samples.")
        return 1
    step("أحمّل قارئ النص ونموذج الترجمة...")
    ocr = OcrEngine()
    name = engine or default_engine_name()
    try:
        mt = ENGINES[name]()
    except (KeyError, TranslateError) as exc:
        warn(str(exc))
        return 1
    mt.translate("Hello.")
    results: dict[str, list[float]] = {k: [] for k in ("detect", "ocr", "mt", "render", "fill", "png")}
    blocks = []
    for frame in frames:
        block = detect(frame)
        if block is None:
            continue
        blocks.append((frame, block))
        ocr.read(frame, block)  # warm-up
        for _ in range(30):
            t = time.perf_counter()
            detect(frame)
            results["detect"].append((time.perf_counter() - t) * 1000)
        for _ in range(8):
            t = time.perf_counter()
            ocr.read(frame, block)
            results["ocr"].append((time.perf_counter() - t) * 1000)
        for _ in range(10):
            t = time.perf_counter()
            fill = render.make_fill(frame, block)
            t1 = time.perf_counter()
            text = render.make_text(frame, block, "هذا سطر تجريبي لقياس سرعة رسم الترجمة العربية.")
            t2 = time.perf_counter()
            fill.png(), text.png()
            t3 = time.perf_counter()
            results["fill"].append((t1 - t) * 1000)
            results["png"].append((t3 - t2) * 1000)
            results["render"].append((t3 - t) * 1000)
    if not blocks:
        warn("ما انكشف نص ترجمة في اللقطات.")
        return 1
    for line in TEST_LINES:
        t = time.perf_counter()
        mt.translate(line)
        results["mt"].append((time.perf_counter() - t) * 1000)

    labels = {
        "detect": "الكشف (لكل صورة)", "ocr": "قراءة سطر الترجمة", "mt": f"الترجمة المحلية ({name})",
        "render": "الرسم + التجهيز (المجموع)", "fill": "  منها: رقعة التغطية", "png": "  منها: ضغط PNG",
    }
    ok("القياسات على هذا اللابتوب (وسيط / p90 / الحد المطلوب):")
    missed = 0
    for key in ("detect", "ocr", "mt", "render", "fill", "png"):
        p50, p90 = _stats(results[key])
        budget = BUDGETS.get(key)
        flag = ""
        if budget is not None:
            if p50 > budget:
                flag = "  ⚠ أعلى من الحد"
                missed += 1
            info(f"{labels[key]}: {p50:.1f} / {p90:.1f} / {budget:.0f} ms{flag}")
        else:
            info(f"{labels[key]}: {p50:.1f} / {p90:.1f} ms")
    cv2.setNumThreads(cv2.getNumThreads())
    if missed:
        warn(f"{missed} مرحلة أبطأ من المطلوب على هذا الجهاز (تنبيه فقط).")
    return 0
