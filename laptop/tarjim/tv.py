"""`tarjim tv build | setup | test | revert`: everything that touches the TV."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time

from PIL import Image

from . import paths, patterns
from .adb import A11Y_SERVICE, OVERLAY_SERVICE, PACKAGE, Adb, AdbError
from .say import fail, info, ok, step, warn
from .tvlink import TvLink, TvLinkError


class TvError(Exception):
    pass


def _serial(ip: str) -> str:
    return ip if ":" in ip else f"{ip}:5555"


def _tv_ip(cfg: dict, ip: str | None) -> str:
    ip = ip or cfg.get("tv_ip")
    if not ip:
        raise TvError("ما عندي عنوان IP للتلفزيون. شغّل: tarjim tv setup --ip <العنوان>")
    return ip


# -- build ----------------------------------------------------------------


def build() -> None:
    jdk = paths.jdk_home()
    sdk = paths.android_sdk()
    if jdk is None or sdk is None:
        raise TvError("ناقص JDK 17 أو Android SDK. شغّل: tarjim doctor")
    project = paths.REPO / "tv-app"
    wrapper = project / ("gradlew.bat" if sys.platform == "win32" else "gradlew")
    env = dict(os.environ, JAVA_HOME=str(jdk), ANDROID_HOME=str(sdk), ANDROID_SDK_ROOT=str(sdk))
    step("أبني تطبيق التلفزيون (أول مرة تاخذ كم دقيقة)...")
    proc = subprocess.run([str(wrapper), "--no-daemon", "-q", "assembleDebug"], cwd=project, env=env)
    if proc.returncode != 0 or not paths.APK.exists():
        raise TvError("فشل بناء تطبيق التلفزيون.")
    ok(f"التطبيق جاهز: {paths.APK}")


# -- setup ----------------------------------------------------------------


def connect(adb: Adb, wait_s: float = 90.0) -> None:
    """adb connect, then wait for the user to accept the debugging prompt."""
    out = adb.run("connect", adb.serial, check=False)
    if "refused" in out or "cannot connect" in out or "failed to connect" in out:
        raise TvError(
            "التلفزيون رفض الاتصال على المنفذ 5555.\n"
            "في التلفزيون: الإعدادات > النظام > خيارات المطوّر > فعّل «تصحيح أخطاء USB» "
            "(أو «تصحيح الأخطاء اللاسلكي»)، وتأكد إن عنوان الـIP صحيح."
        )
    asked = False
    deadline = time.monotonic() + wait_s
    while True:
        state = _device_state(adb)
        if state == "device":
            return
        if state == "unauthorized" and not asked:
            info("شوف شاشة التلفزيون: بتطلع رسالة «السماح بتصحيح الأخطاء؟» — اختر «السماح دائماً من هذا الكمبيوتر» ثم موافق.")
            asked = True
        if time.monotonic() > deadline:
            raise TvError(f"ما قدرت أتصل بالتلفزيون (الحالة: {state or 'غير موجود'}).")
        time.sleep(2.0)
        if state != "unauthorized":
            adb.run("connect", adb.serial, check=False)


def _device_state(adb: Adb) -> str | None:
    for line in adb.run("devices").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[0] == adb.serial:
            return parts[1]
    return None


def read_tv_facts(adb: Adb) -> dict:
    return {
        "model": adb.run("shell", "getprop", "ro.product.model"),
        "brand": adb.run("shell", "getprop", "ro.product.brand"),
        "sdk": adb.run("shell", "getprop", "ro.build.version.sdk"),
        "release": adb.run("shell", "getprop", "ro.build.version.release"),
        "wm_size": adb.run("shell", "wm", "size"),
        "wm_density": adb.run("shell", "wm", "density"),
    }


def _a11y_list(value: str) -> list[str]:
    value = value.strip()
    if value in ("", "null"):
        return []
    return [v for v in value.split(":") if v]


def setup(ip: str | None) -> None:
    cfg = paths.load_config()
    ip = _tv_ip(cfg, ip)
    if not paths.APK.exists():
        build()
    adb = Adb(_serial(ip))

    step("أتصل بالتلفزيون...")
    connect(adb)
    facts = read_tv_facts(adb)
    cfg.update(tv_ip=ip, tv=facts)
    paths.save_config(cfg)
    ok(f"متصل: {facts['brand']} {facts['model']} — Android {facts['release']} (API {facts['sdk']})")

    step("أثبّت تطبيق ترجِم على التلفزيون...")
    adb.run("install", "-r", str(paths.APK), timeout=180)
    if PACKAGE not in adb.run("shell", "pm", "path", PACKAGE):
        raise TvError("التثبيت ما نجح.")

    step("أعطي التطبيق صلاحية الرسم فوق الشاشة...")
    adb.run("shell", "appops", "set", PACKAGE, "SYSTEM_ALERT_WINDOW", "allow")
    appop = adb.run("shell", "appops", "get", PACKAGE, "SYSTEM_ALERT_WINDOW")
    if "allow" not in appop:
        warn(f"صلاحية النافذة A ما تأكدت ({appop}). نكمل بالنافذة B.")

    step("أفعّل خدمة النافذة الثانية (B)...")
    old_list = adb.run("shell", "settings", "get", "secure", "enabled_accessibility_services")
    old_enabled = adb.run("shell", "settings", "get", "secure", "accessibility_enabled")
    state = _load_state()
    if "a11y_services_before" not in state:  # keep the very first backup
        state.update(a11y_services_before=old_list, a11y_enabled_before=old_enabled, tv_ip=ip)
        paths.write_private(paths.TV_STATE_FILE, json.dumps(state, indent=2))
    services = _a11y_list(old_list)
    if A11Y_SERVICE not in services:
        services.append(A11Y_SERVICE)  # append: never drop the user's other services
        adb.run("shell", "settings", "put", "secure", "enabled_accessibility_services", f"'{':'.join(services)}'")
    adb.run("shell", "settings", "put", "secure", "accessibility_enabled", "1")
    readback = adb.run("shell", "settings", "get", "secure", "enabled_accessibility_services")
    if A11Y_SERVICE not in _a11y_list(readback):
        warn("خدمة النافذة B ما تفعّلت. نكمل بالنافذة A.")

    start_service(adb)
    step("أجرّب الاتصال بالتطبيق...")
    caps = _wait_for_app(ip)
    cfg["overlay"] = {k: caps.get(k) for k in ("w", "h", "density", "sdk", "model", "windows")}
    paths.save_config(cfg)
    ok(f"التطبيق شغّال. مساحة الرسم {caps['w']}x{caps['h']}، النوافذ المتاحة: {', '.join(caps['windows']) or 'ولا وحدة'}")
    if not caps["windows"]:
        raise TvError("التطبيق شغّال لكن ما فيه ولا نافذة رسم متاحة.")


def start_service(adb: Adb) -> None:
    adb.run("shell", "am", "start-foreground-service", "-n", OVERLAY_SERVICE)
    services = adb.run("shell", "dumpsys", "activity", "services", PACKAGE)
    if "OverlayService" not in services:
        raise TvError("خدمة التطبيق ما اشتغلت على التلفزيون.")


def _wait_for_app(ip: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        link = TvLink(ip, auto_reconnect=False)
        try:
            caps = link.connect(timeout=2.0)
            link.close()
            if caps.get("windows"):
                return caps
            last = TvLinkError("no windows yet")
        except TvLinkError as exc:
            last = exc
        time.sleep(0.5)
    raise TvError(f"ما قدرت أكلّم التطبيق على التلفزيون: {last}")


# -- test -----------------------------------------------------------------


def test(ip: str | None, seconds: int, selfcheck: bool) -> bool:
    cfg = paths.load_config()
    ip = _tv_ip(cfg, ip)
    adb = Adb(_serial(ip))
    connect(adb, wait_s=20)
    start_service(adb)
    caps = _wait_for_app(ip)
    pats = patterns.make_patterns(caps["w"], caps["h"])
    active = [pats[w] for w in caps["windows"] if w in pats]
    passed = True
    with TvLink(ip) as link:
        link.connect()
        timings = []
        for p in active:
            seq = link.show(p.win, [patterns.pattern_layer(p)])
            ack = link.wait_ack(seq)
            if ack is None or ack.get("t_drawn") is None:
                raise TvError(f"التلفزيون ما رسم النمط {p.win} ({(ack or {}).get('status', 'بدون رد')}).")
            timings.append((p.win, ack["t_drawn"] - ack["t_recv"]))
        ids = [f"pattern-{p.win}" for p in active]
        for win, ms in timings:
            info(f"النمط {win}: انرسم خلال {ms:.0f} ms من وصوله للتلفزيون.")
        if selfcheck:
            time.sleep(0.4)
            link.keep(ids)
            passed = _selfcheck(adb, caps, active)
        info(f"الأنماط على الشاشة لمدة {seconds} ثانية: A وردي يسار، B سماوي يمين. (Ctrl+C للإيقاف)")
        end = time.monotonic() + seconds
        try:
            while time.monotonic() < end:
                link.keep(ids)
                time.sleep(0.3)
        except KeyboardInterrupt:
            pass
        link.clear(None)
    ok("انمسحت الأنماط.")
    return passed


def _selfcheck(adb: Adb, caps: dict, active: list[patterns.Pattern]) -> bool:
    step("أصوّر شاشة التلفزيون وأتأكد من مكان الأنماط...")
    try:
        png = adb.run("exec-out", "screencap", "-p", binary=True, timeout=30)
        shot = Image.open(io.BytesIO(png))
        shot.load()
    except (AdbError, OSError) as exc:
        warn(f"ما قدرت أصوّر الشاشة ({exc}). جرّب والتلفزيون على الشاشة الرئيسية.")
        return False
    out = paths.REPO / "out"
    out.mkdir(exist_ok=True)
    path = out / f"tv-selfcheck-{time.strftime('%Y%m%d-%H%M%S')}.png"
    shot.save(path)
    result = patterns.check_screencap(shot, caps["w"], caps["h"], active)
    all_ok = True
    for win, r in result.items():
        if r["ok"]:
            ok(f"النمط {win} في مكانه الصحيح في لقطة الشاشة.")
        else:
            all_ok = False
            warn(f"النمط {win} مو ظاهر في لقطة الشاشة: {r['points']}")
    info(f"اللقطة ({shot.width}x{shot.height}) محفوظة: {path}")
    return all_ok


# -- revert ---------------------------------------------------------------


def _load_state() -> dict:
    if paths.TV_STATE_FILE.exists():
        return json.loads(paths.TV_STATE_FILE.read_text(encoding="utf-8"))
    return {}


def revert(ip: str | None) -> None:
    cfg = paths.load_config()
    state = _load_state()
    ip = ip or cfg.get("tv_ip") or state.get("tv_ip")
    if not ip:
        raise TvError("ما عندي عنوان التلفزيون عشان أرجّع الإعدادات.")
    adb = Adb(_serial(ip))
    connect(adb, wait_s=20)

    step("أوقف الخدمة...")
    adb.run("shell", "am", "stopservice", "-n", OVERLAY_SERVICE, check=False)

    step("أشيل خدمتنا من قائمة خدمات الوصول...")
    current = _a11y_list(adb.run("shell", "settings", "get", "secure", "enabled_accessibility_services"))
    remaining = [s for s in current if s != A11Y_SERVICE]
    if remaining:
        adb.run("shell", "settings", "put", "secure", "enabled_accessibility_services", f"'{':'.join(remaining)}'")
    else:
        adb.run("shell", "settings", "delete", "secure", "enabled_accessibility_services")
        before = state.get("a11y_enabled_before", "0").strip()
        adb.run("shell", "settings", "put", "secure", "accessibility_enabled", "1" if before == "1" else "0")

    step("أرجّع الصلاحية وأحذف التطبيق...")
    if PACKAGE in adb.run("shell", "pm", "path", PACKAGE, check=False):
        adb.run("shell", "appops", "set", PACKAGE, "SYSTEM_ALERT_WINDOW", "default", check=False)
        adb.run("uninstall", PACKAGE, check=False)

    after = adb.run("shell", "settings", "get", "secure", "enabled_accessibility_services")
    gone = PACKAGE not in adb.run("shell", "pm", "path", PACKAGE, check=False)
    adb.run("disconnect", adb.serial, check=False)
    if gone and A11Y_SERVICE not in after:
        if paths.TV_STATE_FILE.exists():
            paths.TV_STATE_FILE.unlink()
        ok("رجع التلفزيون مثل ما كان: التطبيق انحذف والإعدادات رجعت.")
    else:
        raise TvError(f"الرجوع ما اكتمل (التطبيق محذوف: {gone}، قائمة الخدمات: {after}).")


def run_cli(func, *args) -> int:
    try:
        result = func(*args)
    except (TvError, AdbError, TvLinkError) as exc:
        fail(str(exc))
        return 1
    return 0 if result in (None, True) else 1
