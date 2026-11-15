"""`tarjim doctor`: check every prerequisite and say how to fix it, in Arabic."""

from __future__ import annotations

import socket
import subprocess
import sys

from . import paths
from .protocol import DEFAULT_PORT
from .say import fail, info, ok, warn


def _port_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run() -> int:
    problems = 0

    def bad(msg: str, fix: str) -> None:
        nonlocal problems
        problems += 1
        fail(msg)
        info(f"الحل: {fix}")

    v = sys.version_info
    if (v.major, v.minor) == (3, 12):
        ok(f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        bad(f"Python {v.major}.{v.minor} (المطلوب 3.12)", "شغّل من مجلد laptop: uv sync")

    try:
        from PIL import features

        if features.check("raqm"):
            ok("محرك تشكيل الحروف العربية (RAQM) موجود")
        else:
            warn("محرك RAQM غير موجود في Pillow على هذا الجهاز؛ رسم العربي بيستخدم HarfBuzz (مرحلة M3)")
    except ImportError:
        bad("مكتبة Pillow غير مثبتة", "شغّل من مجلد laptop: uv sync")

    adb = paths.adb_path()
    if adb:
        ok(f"adb: {adb}")
    else:
        bad("adb غير موجود", "نزّل Android platform-tools داخل ‎.tools/platform-tools")

    jdk = paths.jdk_home()
    if jdk:
        out = subprocess.run([str(jdk / "bin" / "java"), "-version"], capture_output=True, text=True)
        ok(f"Java: {(out.stderr or out.stdout).splitlines()[0]}")
    else:
        bad("JDK 17 غير موجود", "نزّل Temurin JDK 17 داخل ‎.tools/jdk17")

    sdk = paths.android_sdk()
    platforms = sorted(p.name for p in (sdk / "platforms").iterdir()) if sdk and (sdk / "platforms").exists() else []
    if platforms:
        ok(f"Android SDK: {', '.join(platforms)}")
    else:
        bad("حزم Android SDK غير مثبتة (لازم الموافقة على الرخص)", "شغّل: tarjim sdk install")

    if paths.APK.exists():
        ok("تطبيق التلفزيون مبني")
    else:
        bad("تطبيق التلفزيون ما انبنى للحين", "شغّل: tarjim tv build")

    cfg = paths.load_config()
    ip = cfg.get("tv_ip")
    if not ip:
        bad("عنوان IP للتلفزيون غير محفوظ", "شغّل: tarjim tv setup --ip <عنوان التلفزيون>")
    else:
        if _port_open(ip, 5555):
            ok(f"التلفزيون {ip}: منفذ adb مفتوح")
        else:
            bad(
                f"التلفزيون {ip}: منفذ adb (5555) ما يرد",
                "تأكد إن التلفزيون شغّال وعلى نفس الشبكة وإن تصحيح الأخطاء مفعّل في خيارات المطوّر",
            )
        if _port_open(ip, DEFAULT_PORT):
            ok("تطبيق ترجِم على التلفزيون يرد")
        else:
            warn("تطبيق ترجِم على التلفزيون ما يرد (طبيعي قبل tarjim tv setup)")

    if problems:
        fail(f"فيه {problems} نقطة تحتاج حل.")
        return 1
    ok("كل شي جاهز.")
    return 0
