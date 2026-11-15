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
    info("أمر غير معروف.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
