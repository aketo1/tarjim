"""The `tarjim` command."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from . import __version__, paths
from .say import fail, info, ok, setup_console, step


def _sdk_install() -> int:
    """Install the Android SDK packages. The user answers the licence prompts themselves."""
    jdk, sdk = paths.jdk_home(), paths.android_sdk()
    if jdk is None or sdk is None:
        fail("ناقص JDK أو أدوات Android. شغّل: tarjim doctor")
        return 1
    name = "sdkmanager.bat" if sys.platform == "win32" else "sdkmanager"
    manager = sdk / "cmdline-tools" / "latest" / "bin" / name
    env = dict(os.environ, JAVA_HOME=str(jdk))
    step("بتطلع لك رخص Android SDK من قوقل. اقرأها واكتب y ثم Enter للموافقة على كل وحدة.")
    if subprocess.run([str(manager), f"--sdk_root={sdk}", "--licenses"], env=env).returncode != 0:
        fail("ما اكتملت الموافقة على الرخص.")
        return 1
    packages = ["platforms;android-36", "build-tools;36.0.0"]
    if subprocess.run([str(manager), f"--sdk_root={sdk}", *packages], env=env).returncode != 0:
        fail("فشل تنزيل حزم Android SDK.")
        return 1
    if not (sdk / "platforms" / "android-36").exists():
        fail("الحزم ما تثبتت (غالباً الرخص ما انقبلت).")
        return 1
    ok("حزم Android SDK جاهزة.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tarjim", description="ترجِم: ترجمة عربية فوق ألعاب PS5 على التلفزيون")
    parser.add_argument("--version", action="version", version=f"tarjim {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="يفحص كل المتطلبات")

    sdk = sub.add_parser("sdk", help="أدوات Android").add_subparsers(dest="sdk_cmd", required=True)
    sdk.add_parser("install", help="ينزّل حزم Android SDK (يطلب موافقتك على الرخص)")

    tv = sub.add_parser("tv", help="تطبيق التلفزيون").add_subparsers(dest="tv_cmd", required=True)
    tv.add_parser("build", help="يبني تطبيق التلفزيون")
    p = tv.add_parser("setup", help="يثبّت التطبيق ويفعّله على التلفزيون")
    p.add_argument("--ip", help="عنوان IP للتلفزيون")
    p = tv.add_parser("test", help="يعرض نمطين A و B على التلفزيون")
    p.add_argument("--ip")
    p.add_argument("--seconds", type=int, default=60, help="كم ثانية تبقى الأنماط")
    p.add_argument("--no-selfcheck", action="store_true", help="بدون تصوير الشاشة")
    p = tv.add_parser("revert", help="يرجّع التلفزيون مثل ما كان")
    p.add_argument("--ip")

    src = sub.add_parser("source", help="صورة الـPS5").add_subparsers(dest="src_cmd", required=True)
    p = src.add_parser("setup", help="يربط اللابتوب بالـPS5 (حساب ثاني + رقم الربط)")
    p.add_argument("--host", help="عنوان IP للـPS5")
    p.add_argument("--redirect-url", help="عنوان صفحة redirect بعد تسجيل الدخول عند Sony")
    p.add_argument("--pin", help="رقم الربط من الـPS5 (8 أرقام)")
    p = src.add_parser("test", help="يقيس الدقة وعدد الصور والانقطاعات")
    p.add_argument("--backend", default="rp-pyremoteplay", choices=["rp-pyremoteplay", "file"])
    p.add_argument("--seconds", type=float, default=30)
    p.add_argument("--path", help="صورة أو مجلد صور أو فيديو (للمصدر file)")
    p.add_argument("--host")

    p = sub.add_parser("preview", help="يجرّب كل شي على ملف بدون تلفزيون ويحفظ النتيجة")
    p.add_argument("path", help="صورة أو مجلد صور أو فيديو")
    p.add_argument("--engine", help="محرك الترجمة: nllb-600m أو opus-big")
    p.add_argument("--fps", type=float, default=30)
    bench = sub.add_parser("bench", help="قياسات").add_subparsers(dest="bench_cmd", required=True)
    p = bench.add_parser("latency", help="يقيس سرعة كل مرحلة على هذا اللابتوب")
    p.add_argument("--engine")
    p = sub.add_parser("app", help="يفتح تطبيق ترجِم (الواجهة)")
    p.add_argument("--no-window", action="store_true", help="بدون فتح النافذة")
    p = sub.add_parser("run", help="يشغّل الترجمة الحية على التلفزيون")
    p.add_argument("--profile", default="default")
    p.add_argument("--engine")
    p.add_argument("--no-fill", action="store_true", help="بدون تغطية الإنجليزي (العربي فقط)")
    p.add_argument("--seconds", type=float, default=0, help="يوقف لحاله بعد هذي المدة (0 = بدون حد)")
    return parser


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("PYTHONUTF8", "1")
    setup_console()
    args = build_parser().parse_args(argv)
    if args.cmd == "doctor":
        from . import doctor

        return doctor.run()
    if args.cmd == "sdk":
        return _sdk_install()
    if args.cmd == "tv":
        from . import tv

        if args.tv_cmd == "build":
            return tv.run_cli(tv.build)
        if args.tv_cmd == "setup":
            return tv.run_cli(tv.setup, args.ip)
        if args.tv_cmd == "test":
            return tv.run_cli(tv.test, args.ip, args.seconds, not args.no_selfcheck)
        if args.tv_cmd == "revert":
            return tv.run_cli(tv.revert, args.ip)
    if args.cmd == "source":
        from . import source_cli

        if args.src_cmd == "setup":
            return source_cli.setup(args.host, args.redirect_url, args.pin)
        if args.src_cmd == "test":
            return source_cli.test(args.backend, args.seconds, args.path, args.host)
    if args.cmd == "preview":
        from . import run_cli

        return run_cli.preview(args.path, args.engine, args.fps)
    if args.cmd == "bench":
        from . import bench

        return bench.latency(args.engine)
    if args.cmd == "app":
        from .app import server

        return server.main(window=not args.no_window)
    if args.cmd == "run":
        from . import run_cli

        return run_cli.run(args.profile, args.engine, args.no_fill, args.seconds)
    info("أمر غير معروف.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
