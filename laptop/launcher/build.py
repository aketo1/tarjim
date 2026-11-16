"""Build Tarjim.exe (the program's own executable) into the repo root.

Uses csc.exe, the C# compiler that is part of every Windows installation
(.NET Framework 4), so nothing has to be downloaded.

    python launcher/build.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ICON = HERE.parent / "tarjim" / "app" / "web" / "icon.ico"
OUT = REPO / "Tarjim.exe"


def compiler() -> Path | None:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    path = windir / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
    return path if path.exists() else None


def build() -> Path:
    csc = compiler()
    if csc is None:
        raise RuntimeError("csc.exe (.NET Framework 4, 64-bit) was not found")
    cmd = [
        str(csc), "/nologo", "/target:winexe", "/platform:x64", "/optimize+", "/codepage:65001",
        f"/win32icon:{ICON}", f"/out:{OUT}", str(HERE / "Tarjim.cs"),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, creationflags=0x08000000)
    if proc.returncode != 0 or not OUT.exists():
        raise RuntimeError(f"building Tarjim.exe failed:\n{proc.stdout}\n{proc.stderr}")
    return OUT


if __name__ == "__main__":
    if sys.platform != "win32":
        sys.exit("Windows only")
    print(build())
