"""Create the desktop and Start-menu shortcuts that open the app without a console window."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

WEB = Path(__file__).parent / "web"


def _shortcut_dirs() -> list[Path]:
    home = Path.home()
    dirs = [home / "Desktop", home / "OneDrive" / "Desktop"]
    appdata = os.environ.get("APPDATA")
    if appdata:
        dirs.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    return [d for d in dirs if d.is_dir()]


def create() -> list[Path]:
    """Returns the shortcut files written. Windows only."""
    if sys.platform != "win32":
        return []
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    icon = WEB / "icon.ico"
    workdir = Path(__file__).resolve().parents[2]
    written = []
    for folder in _shortcut_dirs():
        link = folder / "Tarjim.lnk"
        script = (
            "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:TARJIM_LNK);"
            "$s.TargetPath = $env:TARJIM_EXE; $s.Arguments = '-m tarjim.app';"
            "$s.WorkingDirectory = $env:TARJIM_DIR; $s.IconLocation = $env:TARJIM_ICO;"
            "$s.Description = 'Tarjim'; $s.Save()"
        )
        env = dict(os.environ, TARJIM_LNK=str(link), TARJIM_EXE=str(pythonw), TARJIM_DIR=str(workdir), TARJIM_ICO=str(icon))
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script], env=env, capture_output=True
        )
        if result.returncode == 0 and link.exists():
            written.append(link)
    return written
