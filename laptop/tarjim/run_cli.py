"""`tarjim preview` (FakeTv, no devices) and `tarjim run` (the real thing)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from . import paths
from .faketv import FakeTv
from .pipeline import Pipeline, new_log_path
from .say import fail, info, ok, step, warn
from .sources import SourceError, open_source
from .translate import ENGINES, Cache, CachedTranslator, TranslateError, default_engine_name
from .tvlink import TvLink, TvLinkError
from .vision.tracker import Event


def build_translator(engine: str | None, profile: str, cache_path: str | None = None) -> CachedTranslator:
    name = engine or default_engine_name()
    if name not in ENGINES:
        raise TranslateError(f"unknown engine {name!r}; choose from {', '.join(ENGINES)}")
    engine_obj = ENGINES[name]()
    engine_obj.translate("Hello.")  # warm-up: the first call is several times slower
    return CachedTranslator(engine_obj, Cache(cache_path), profile=profile)


def _print_summary(pipe: Pipeline) -> None:
    labels = {
        "detect": "الكشف والتتبّع (لكل صورة)", "ocr": "قراءة النص", "mt": "الترجمة", "mt_cached": "الترجمة (من الذاكرة)",
        "render": "الرسم والتجهيز", "tv": "الإرسال والرسم على التلفزيون", "total": "من ثبات السطر إلى ظهوره",
        "refresh": "تحديث الرقعة",
    }
    info(f"سطور انعرضت: {pipe.lines_shown} — سطور انرفضت: {pipe.rejected}")
    for name, s in pipe.times.summary().items():
        info(f"  {labels.get(name, name)}: وسيط {s['p50']:.0f} ms، p90 {s['p90']:.0f} ms ({s['n']})")


def preview(path: str, engine: str | None, fps: float) -> int:
    """Run the pipeline on files against FakeTv and save what the TV would show."""
    out = paths.REPO / "out" / "preview"
    out.mkdir(parents=True, exist_ok=True)
    try:
        step("أحمّل قارئ النص ونموذج الترجمة...")
        translator = build_translator(engine, "default")
        source = open_source("file", path=path, fps=fps)
    except (TranslateError, SourceError) as exc:
        fail(str(exc))
        return 1
    saved = 0
    with FakeTv() as tv, TvLink(tv.host, tv.port) as link:
        link.connect()
        pipe = Pipeline(link, translator, log_path=new_log_path())
        is_still = Path(path).is_file() and Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        frames = source.frames()
        if is_still:  # one image: repeat it so the line can settle
            frame0 = next(frames)[0]
            if frame0.shape[0] != 1080:
                frame0 = cv2.resize(frame0, (1920, 1080), interpolation=cv2.INTER_AREA)
            frames = ((frame0, time.monotonic(), i) for i in range(1, 12) if not time.sleep(0.04))
        for frame, t_capture, seq in frames:
            event = pipe.process(frame, t_capture)
            if event is Event.NEW and pipe.lines_shown > saved:
                link.wait_ack(link._seq, timeout=1.0)
                shot = tv.composite(Image.fromarray(np.ascontiguousarray(frame[:, :, ::-1])))
                target = out / f"{Path(path).stem}-{pipe.lines_shown:03d}.png"
                shot.convert("RGB").save(target)
                saved = pipe.lines_shown
                ok(f"سطر {saved}: {target}")
        pipe.close()
        _print_summary(pipe)
    if saved == 0:
        warn("ما انكشف أي سطر ترجمة في هذا الملف.")
        return 1
    return 0


def _key_pressed() -> str | None:
    if sys.platform == "win32":
        import msvcrt

        if msvcrt.kbhit():
            return msvcrt.getwch().lower()
    return None


def run(profile: str, engine: str | None, no_fill: bool, seconds: float = 0.0) -> int:
    from . import tv as tvmod
    from .adb import Adb, AdbError

    cfg = paths.load_config()
    ip = cfg.get("tv_ip")
    if not ip:
        fail("التلفزيون مو مجهّز. شغّل: tarjim tv setup --ip <عنوان التلفزيون>")
        return 1
    try:
        step("أحمّل قارئ النص ونموذج الترجمة...")
        translator = build_translator(engine, profile)
        step("أشغّل تطبيق التلفزيون...")
        adb = Adb(ip if ":" in ip else f"{ip}:5555")
        tvmod.connect(adb, wait_s=20)
        tvmod.start_service(adb)
        caps = tvmod._wait_for_app(ip)
        step("أتصل بصورة الـPS5...")
        source = open_source("rp-pyremoteplay")
    except (TranslateError, SourceError, tvmod.TvError, AdbError, TvLinkError) as exc:
        fail(str(exc))
        return 1
    window = cfg.get("window") or ("A" if "A" in caps["windows"] else caps["windows"][0])
    link = TvLink(ip)
    pipe = None
    try:
        link.connect()
        pipe = Pipeline(link, translator, window=window, log_path=new_log_path(), show_fill=not no_fill)
        ok("ترجِم شغّال. المفاتيح: o تشغيل/إيقاف الترجمة، q خروج.")
        last_info = started = time.monotonic()
        for frame, t_capture, _seq in source.frames():
            if seconds and time.monotonic() - started >= seconds:
                break
            event = pipe.process(frame, t_capture)
            if event is Event.NEW and pipe._pending:
                rec = list(pipe._pending.values())[-1]
                info(f"{rec['en']}  ←  {rec['ar']}")
            key = _key_pressed()
            if key == "q":
                break
            if key == "o":
                pipe.set_enabled(not pipe.enabled)
                info("الترجمة شغّالة" if pipe.enabled else "الترجمة موقّفة")
            if time.monotonic() - last_info > 60:
                last_info = time.monotonic()
                i = source.info()
                info(f"  المصدر: {i.fps:.0f} صورة/ثانية، انقطاعات {i.reconnects}")
    except KeyboardInterrupt:
        pass
    except (SourceError, TvLinkError) as exc:
        fail(str(exc))
    finally:
        if pipe is not None:
            pipe.close()
            _print_summary(pipe)
        link.close()  # sends a clear; the TV also clears by itself within 1 s
        source.close()
        ok("توقف ترجِم وانمسحت الشاشة.")
    return 0
