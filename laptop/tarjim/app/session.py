"""What the app runs behind its buttons: the live session and the setup tasks.

Everything reports through a `Hub`, which fans events out to the open windows
(server-sent events). Nothing here prints for the user; messages are Arabic
strings the interface shows as they are.
"""

from __future__ import annotations

import queue
import statistics
import threading
import time

from .. import paths, say


class Hub:
    """Fan-out of (kind, data) events to every connected window."""

    def __init__(self) -> None:
        self._subs: set[queue.Queue] = set()
        self._lock = threading.Lock()
        self.last_client_seen = time.monotonic()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=400)
        with self._lock:
            self._subs.add(q)
            self.last_client_seen = time.monotonic()
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subs.discard(q)
            self.last_client_seen = time.monotonic()

    @property
    def clients(self) -> int:
        with self._lock:
            return len(self._subs)

    def publish(self, kind: str, data: dict) -> None:
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait((kind, data))
            except queue.Full:
                pass  # a stuck window loses events rather than blocking the session


def friendly_error(exc: Exception) -> str:
    """Turn a technical failure into one plain Arabic sentence with the next step."""
    text = str(exc)
    low = text.lower()
    if "5555" in text or "التلفزيون رفض" in text or "ما قدرت أتصل بالتلفزيون" in text:
        return "ما قدرت أوصل للتلفزيون. تأكد إنه شغّال وعلى نفس الشبكة، ثم جرّب مرة ثانية."
    if "ما قدرت أكلّم التطبيق" in text:
        return "تطبيق ترجِم على التلفزيون ما يرد. افتح «الدليل» وأعد تجهيز التلفزيون."
    if "rest mode" in low:
        return "الـPS5 في وضع الراحة. شغّله ثم جرّب."
    if "no answer from the console" in low or "no ps5" in low:
        return "ما لقيت الـPS5 على الشبكة. تأكد إنه شغّال وعلى نفس الشبكة."
    if "not linked" in low or "source setup" in low:
        return "اللابتوب مو مربوط بالـPS5. افتح «الدليل» وكمّل خطوة ربط الـPS5."
    if "translation model missing" in low:
        return "ملفات الترجمة ناقصة من مجلد models."
    if "session refused" in low or "did not become ready" in low:
        return "الـPS5 رفض الاتصال. تأكد إن «اللعب عن بُعد» مفعّل وإن الحساب الثاني مسجّل دخوله على الجهاز."
    return text or type(exc).__name__


class LiveSession:
    """Starts, watches and stops the live translation. One at a time."""

    STEPS = [("models", "أحمّل القارئ والمترجم"), ("tv", "أشغّل تطبيق التلفزيون"), ("ps5", "أتصل بصورة الـPS5")]

    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.state = "idle"  # idle | starting | running | stopping
        self.step = ""
        self.error = ""
        self.profile = ""
        self.lines: list[dict] = []
        self.stats: dict = {}
        self.started_at = 0.0  # wall-clock time the picture first arrived (0: not running)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._source = None
        self._pipe = None
        self._ocr = None
        self._engines: dict[str, object] = {}
        self._lock = threading.Lock()

    def snapshot(self) -> dict:
        return {
            "state": self.state, "step": self.step, "error": self.error, "profile": self.profile,
            "lines": self.lines[-30:], "stats": self.stats, "started_at": self.started_at,
        }

    def _set(self, state: str, step: str = "", error: str = "") -> None:
        self.state, self.step, self.error = state, step, error
        if state == "running" and not self.started_at:
            self.started_at = time.time()
        elif state == "idle":
            self.started_at = 0.0
        self.hub.publish("state", {"state": state, "step": step, "error": error, "profile": self.profile,
                                   "started_at": self.started_at})

    def start(self, profile: str) -> bool:
        with self._lock:
            if self.state != "idle":
                return False
            self.profile = profile
            self.lines = []
            self.stats = {}
            self._stop.clear()
            self._set("starting", "models")
            self._thread = threading.Thread(target=self._run, args=(profile,), name="tarjim-live", daemon=True)
            self._thread.start()
            return True

    def stop(self) -> None:
        with self._lock:
            if self.state in ("idle", "stopping"):
                return
            self._stop.set()
            self._set("stopping", self.step)
            source = self._source
        if source is not None:
            threading.Thread(target=source.close, daemon=True).start()  # unblocks the frame loop

    def frame_jpeg(self, width: int = 960) -> bytes | None:
        """The newest picture from the PS5, small, for the region editor. None when not running."""
        import cv2

        pipe = self._pipe
        frame = getattr(pipe, "_latest", None) if pipe is not None else None
        if frame is None:
            return None
        h = int(round(frame.shape[0] * width / frame.shape[1]))
        small = cv2.resize(frame, (width, h), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 78])
        return buf.tobytes() if ok else None

    def apply_profile(self, name: str) -> bool:
        """Apply saved look settings to the running session at once (no restart)."""
        import dataclasses

        from .. import settings
        from ..translate import load_profile

        pipe = self._pipe
        if pipe is None or self.state != "running" or name != self.profile:
            return False
        prof = load_profile(name)
        style = settings.make_style(prof, paths.load_config().get("font_sizes", {}).get(name))
        with pipe._lock:
            if style.fixed_size is None and pipe.style.fixed_size:
                style = dataclasses.replace(style, fixed_size=pipe.style.fixed_size)  # keep the measured size
            pipe.style = style
            pipe.background = settings.background(prof)
            pipe.plate_opacity = settings.plate_opacity(prof)
            pipe.read_scale = float(prof.get("read_scale", 1.0))
            pipe.detect_params = settings.detect_params(prof)
            pipe.translator.glossary = {str(k): str(v) for k, v in (prof.get("glossary") or {}).items()}
            pipe.translator.female = {str(n) for n in (prof.get("female") or [])}
        # New names are tried against the engine now, off the frame loop, so no line waits for it.
        threading.Thread(target=self._prepare_names, args=(pipe.translator,), daemon=True).start()
        return True

    @staticmethod
    def _prepare_names(translator) -> None:
        try:
            translator.prepare_names()
        except Exception:
            pass  # a name that could not be tried is simply translated the plain way

    def fix_line(self, profile: str, english: str, arabic: str) -> None:
        """The user rewrote a line: remember it, and correct it in the list on screen."""
        from ..translate import Cache, normalize_arabic, normalize_english

        ar = normalize_arabic(arabic)
        cache = Cache()
        try:
            cache.put_fix(profile, normalize_english(english), ar or None)
        finally:
            cache.close()
        if ar:
            for item in self.lines:
                if item["en"] == english:
                    item["ar"] = ar

    # -- the session thread ---------------------------------------------------

    def _run(self, profile: str) -> None:
        from .. import tv as tvmod
        from ..adb import Adb
        from ..pipeline import Pipeline, new_log_path
        from ..sources import open_source
        from ..translate import Cache, CachedTranslator, default_engine_name, load_profile, make_engine
        from ..tvlink import TvLink
        from ..vision.ocr import OcrEngine
        from ..vision.tracker import TrackParams

        link = pipe = None
        error = ""
        try:
            paths.boost_process()
            cfg = paths.load_config()
            prof = load_profile(profile)
            ip = cfg.get("tv_ip")
            if not ip:
                raise RuntimeError("التلفزيون مو مجهّز للحين. افتح «الدليل» وكمّل خطوة التلفزيون.")

            if self._ocr is None:
                self._ocr = OcrEngine()
            name = str(prof.get("engine") or cfg.get("mt_engine") or default_engine_name())
            if name not in self._engines:
                engine = make_engine(name)
                engine.translate("Hello.")  # warm-up
                self._engines[name] = engine
            glossary = {str(k): str(v) for k, v in (prof.get("glossary") or {}).items()}
            translator = CachedTranslator(self._engines[name], Cache(), profile=profile,
                                          style=str(prof.get("style", "msa")), glossary=glossary,
                                          female={str(n) for n in (prof.get("female") or [])})
            translator.prepare_names()  # first time for a game: a few seconds; afterwards remembered
            if self._stop.is_set():
                return

            self._set("starting", "tv")
            adb = Adb(ip if ":" in ip else f"{ip}:5555")
            tvmod.connect(adb, wait_s=20)
            tvmod.start_service(adb)
            caps = tvmod._wait_for_app(ip)
            if self._stop.is_set():
                return

            self._set("starting", "ps5")
            source = open_source("rp-pyremoteplay")
            self._source = source
            link = TvLink(ip)
            link.connect()
            window = cfg.get("window") or ("A" if "A" in caps["windows"] else caps["windows"][0])
            from .. import settings

            style = settings.make_style(prof, cfg.get("font_sizes", {}).get(profile))
            pipe = Pipeline(
                link, translator, self._ocr, window=window, log_path=new_log_path(), style=style,
                track_params=TrackParams(settle_ms=float(prof.get("settle_ms", 60))),
                background=settings.background(prof), plate_opacity=settings.plate_opacity(prof),
                read_scale=float(prof.get("read_scale", 1.0)), detect_params=settings.detect_params(prof),
            )
            self._pipe = pipe

            def on_line(en: str, ar: str) -> None:
                item = {"en": en, "ar": ar, "t": time.time()}
                self.lines.append(item)
                del self.lines[:-60]
                self.hub.publish("line", item)

            def on_size(value: int) -> None:
                fresh = paths.load_config()
                fresh.setdefault("font_sizes", {})[profile] = int(value)
                paths.save_config(fresh)

            pipe.on_line = on_line
            pipe.on_size_locked = on_size

            last_stats = 0.0
            first = True
            for frame, t_capture, _seq in source.frames():
                if self._stop.is_set():
                    break
                if first:
                    first = False
                    self._set("running")
                pipe.process(frame, t_capture)
                now = time.monotonic()
                if now - last_stats >= 1.0:
                    last_stats = now
                    info = source.info()
                    recent = pipe.times.first[-25:]
                    self.stats = {
                        "fps": round(info.fps), "reconnects": info.reconnects, "lines": pipe.lines_shown,
                        "latency_ms": round(statistics.median(recent)) if recent else None,
                        "width": info.width, "height": info.height, "on_battery": paths.on_battery(),
                    }
                    self.hub.publish("stats", self.stats)
            if first and not self._stop.is_set():
                raise RuntimeError(getattr(source, "last_error", None) or "ما وصلت صورة من الـPS5.")
        except Exception as exc:
            error = friendly_error(exc)
        finally:
            for closer in (
                (lambda: pipe.close()) if pipe is not None else None,
                (lambda: link.close()) if link is not None else None,
                (lambda: self._source.close()) if self._source is not None else None,
            ):
                if closer is not None:
                    try:
                        closer()
                    except Exception:
                        pass  # shutting down: the TV clears itself within a second anyway
            self._source = None
            self._pipe = None
            self._set("idle", "", error)


class Tasks:
    """One background setup task at a time (TV setup, test patterns, PS5 linking)."""

    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.name = ""
        self.running = False
        self.log: list[dict] = []
        self._lock = threading.Lock()

    def snapshot(self) -> dict:
        return {"name": self.name, "running": self.running, "log": self.log[-40:]}

    def _say(self, kind: str, msg: str) -> None:
        item = {"kind": kind, "msg": msg}
        self.log.append(item)
        self.hub.publish("task", {"name": self.name, "running": True, "item": item})

    def run(self, name: str, fn) -> bool:
        with self._lock:
            if self.running:
                return False
            self.name, self.running, self.log = name, True, []
        say.set_hook(self._say)

        def work() -> None:
            ok, result = True, None
            try:
                result = fn()
            except Exception as exc:
                ok = False
                self._say("fail", friendly_error(exc))
            finally:
                say.set_hook(None)
                self.running = False
                self.hub.publish("task", {"name": name, "running": False, "ok": ok, "result": result})

        threading.Thread(target=work, name=f"tarjim-task-{name}", daemon=True).start()
        return True
