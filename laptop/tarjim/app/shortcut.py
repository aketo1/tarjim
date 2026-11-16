"""Create the desktop and Start-menu shortcuts.

They point at Tarjim.exe in the repo root (built by launcher/build.py), the
program's own executable: no console window, and Windows shows "Tarjim" with
its icon in the taskbar, when pinned and in Task Manager. If the executable
is missing and cannot be built, the shortcuts fall back to pythonw.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .. import paths

WEB = Path(__file__).parent / "web"
EXE = paths.REPO / "Tarjim.exe"


def _shortcut_dirs() -> list[Path]:
    home = Path.home()
    dirs = [home / "Desktop", home / "OneDrive" / "Desktop"]
    appdata = os.environ.get("APPDATA")
    if appdata:
        dirs.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    return [d for d in dirs if d.is_dir()]


def ensure_exe() -> Path | None:
    if EXE.exists():
        return EXE
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("tarjim_launcher_build", paths.REPO / "laptop" / "launcher" / "build.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.build()
    except Exception:
        return None


def create() -> list[Path]:
    """Returns the shortcut files written. Windows only."""
    if sys.platform != "win32":
        return []
    exe = ensure_exe()
    workdir = Path(__file__).resolve().parents[2]
    if exe is not None:
        target, arguments, icon = exe, "", f"{exe},0"
    else:
        target = Path(sys.executable).with_name("pythonw.exe")
        arguments, icon = "-m tarjim.app", str(WEB / "icon.ico")
    written = []
    for folder in _shortcut_dirs():
        link = folder / "Tarjim.lnk"
        script = (
            "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:TARJIM_LNK);"
            "$s.TargetPath = $env:TARJIM_EXE; $s.Arguments = $env:TARJIM_ARGS;"
            "$s.WorkingDirectory = $env:TARJIM_DIR; $s.IconLocation = $env:TARJIM_ICO;"
            "$s.Description = 'Tarjim'; $s.Save()"
        )
        env = dict(os.environ, TARJIM_LNK=str(link), TARJIM_EXE=str(target), TARJIM_ARGS=arguments,
                   TARJIM_DIR=str(workdir), TARJIM_ICO=icon)
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script],
            env=env, capture_output=True, creationflags=paths.NO_WINDOW,
        )
        if result.returncode == 0 and link.exists():
            written.append(link)
    return written
