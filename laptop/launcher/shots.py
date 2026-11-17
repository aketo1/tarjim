"""Take screenshots of the running app for review: python launcher/shots.py [name ...]

The app must be running (Tarjim.exe, or `tarjim app --no-window`). Pictures go to out/.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "out"
CHROME = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]
SHOTS = {
    "home": ("?still&ok", 1240, 800),
    "home-live": ("?still&demo", 1240, 1240),
    "game": ("?still&view=game", 1240, 2000),
    "phone": ("?still&view=phone", 1240, 800),
    "guide0": ("?still&view=guide&step=0", 1240, 800),
    "guide1": ("?still&view=guide&step=1", 1240, 900),
    "guide3": ("?still&view=guide&step=3", 1240, 900),
    "narrow": ("?still&demo", 1000, 1300),
    "library": ("?still&library", 1240, 900),
    "library-phone": ("?still&library", 520, 900),
    "names": ("?still&view=game&game=rdr2", 1240, 2300),
    "m-home": ("?still&demo", 520, 1900),
    "m-game": ("?still&view=game", 520, 2600),
    "m-guide": ("?still&view=guide&step=2", 520, 1500),
    "m-screen": ("?still&demo&view=screen", 520, 1000),
}


def shoot(name: str, query: str, w: int, h: int, base: str = "http://127.0.0.1:47900/") -> Path:
    chrome = next(c for c in CHROME if Path(c).exists())
    OUT.mkdir(exist_ok=True)
    target = OUT / f"app-{name}.png"
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run([
            chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={profile}",
            f"--window-size={w},{h}", "--virtual-time-budget=6000", f"--screenshot={target}", base + query,
        ], capture_output=True, timeout=90, creationflags=0x08000000)
    return target


if __name__ == "__main__":
    names = sys.argv[1:] or list(SHOTS)
    for n in names:
        print(shoot(n, *SHOTS[n]))
