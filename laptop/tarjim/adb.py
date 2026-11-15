"""A deliberately narrow adb wrapper.

Only the command shapes listed in the project's safety rules can run; anything
else raises before adb is started. Every command is appended to
docs/adb-log.md.
"""

from __future__ import annotations

import datetime as _dt
import re
import subprocess
from pathlib import Path

from . import paths

PACKAGE = "dev.tarjim.tv"
OVERLAY_SERVICE = f"{PACKAGE}/.OverlayService"
A11Y_SERVICE = f"{PACKAGE}/{PACKAGE}.OverlayA11yService"

_SERIAL = r"[0-9A-Za-z\.\-:_]+"
_A11Y_VALUE = r"[A-Za-z0-9_\.\$/:]+"

# Patterns are matched against the arguments joined by single spaces.
_ALLOWED = [
    r"start-server",
    r"devices( -l)?",
    rf"connect {_SERIAL}",
    rf"disconnect {_SERIAL}",
    rf"pair {_SERIAL} \d{{6}}",
    r"install -r \S.*app-debug\.apk",
    rf"uninstall {re.escape(PACKAGE)}",
    r"exec-out screencap -p",
    r"shell getprop( [\w\.]+)?",
    r"shell wm size",
    r"shell wm density",
    r"shell dumpsys (window|activity|display|package|accessibility|SurfaceFlinger|meminfo)( [\w\.\-/ ]+)?",
    r"logcat -d( -t \d+)?( -s [\w:\*\. ]+)?",
    rf"shell pm path {re.escape(PACKAGE)}",
    rf"shell appops get {re.escape(PACKAGE)}( (SYSTEM_ALERT_WINDOW|APP_AUTO_START))?",
    rf"shell appops set {re.escape(PACKAGE)} (SYSTEM_ALERT_WINDOW|APP_AUTO_START) (allow|default)",
    r"shell settings get secure (enabled_accessibility_services|accessibility_enabled)",
    rf"shell settings put secure enabled_accessibility_services '{_A11Y_VALUE}'",
    r"shell settings delete secure enabled_accessibility_services",
    r"shell settings put secure accessibility_enabled [01]",
    rf"shell am start-foreground-service -n {re.escape(OVERLAY_SERVICE)}",
    rf"shell am stopservice -n {re.escape(OVERLAY_SERVICE)}",
]
_ALLOWED_RE = [re.compile(p) for p in _ALLOWED]


class AdbError(Exception):
    pass


class AdbNotAllowed(AdbError):
    pass


def check_allowed(args: list[str]) -> None:
    joined = " ".join(args)
    if "\n" in joined or "\r" in joined:
        raise AdbNotAllowed("adb command not allowed: contains a line break")
    if not any(rx.fullmatch(joined) for rx in _ALLOWED_RE):
        raise AdbNotAllowed(f"adb command not allowed: {joined}")


class Adb:
    def __init__(self, serial: str | None = None, log_file: Path | None = None) -> None:
        exe = paths.adb_path()
        if exe is None:
            raise AdbError("adb not found")
        self.exe = str(exe)
        self.serial = serial
        self.log_file = log_file if log_file is not None else paths.DOCS / "adb-log.md"

    def run(self, *args: str, timeout: float = 30.0, binary: bool = False, check: bool = True):
        """Run one allowed adb command; returns stdout (str, or bytes if binary)."""
        arg_list = list(args)
        check_allowed(arg_list)
        cmd = [self.exe]
        if self.serial and arg_list[0] not in ("connect", "disconnect", "pair", "devices", "start-server"):
            cmd += ["-s", self.serial]
        cmd += arg_list
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            self._log(arg_list, "timeout")
            raise AdbError(f"adb timed out: {' '.join(arg_list)}") from exc
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        self._log(arg_list, f"exit {proc.returncode}")
        if check and proc.returncode != 0:
            out = proc.stdout.decode("utf-8", errors="replace").strip()
            raise AdbError(f"adb {' '.join(arg_list)} failed ({proc.returncode}): {err or out}")
        if binary:
            return proc.stdout
        return proc.stdout.decode("utf-8", errors="replace").strip()

    def _log(self, args: list[str], result: str) -> None:
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_file.exists():
            self.log_file.write_text(
                "# adb command log\n\nEvery adb command Tarjim ran against the TV, oldest first.\n\n",
                encoding="utf-8",
            )
        stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        target = f" [{self.serial}]" if self.serial else ""
        with self.log_file.open("a", encoding="utf-8") as fh:
            fh.write(f"- {stamp}{target} `adb {' '.join(args)}` -> {result}\n")
