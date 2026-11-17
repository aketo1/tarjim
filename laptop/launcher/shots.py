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
# name: (query, width, height). &layout=shelf shows the second layout; without it, "cinema".
SHOTS = {
    "home": ("?still&ok&game=rdr2", 1280, 800),
    "home-shelf": ("?still&ok&game=rdr2&layout=shelf", 1280, 800),
    "home-live": ("?still&demo&game=rdr2", 1280, 800),
    "home-shelf-live": ("?still&demo&game=rdr2&layout=shelf", 1280, 800),
    "games": ("?still&ok&game=rdr2&games", 1280, 800),
    "look": ("?still&ok&view=look&game=rdr2", 1280, 1500),
    "names": ("?still&ok&view=names&game=rdr2", 1280, 1500),
    "phone": ("?still&ok&view=phone", 1280, 800),
    "guide0": ("?still&view=guide&step=0", 1280, 800),
    "guide1": ("?still&view=guide&step=1", 1280, 900),
    "guide3": ("?still&view=guide&step=3", 1280, 900),
    "library": ("?still&ok&library", 1280, 900),
    "narrow": ("?still&demo&game=rdr2", 1000, 680),
    "m-home": ("?still&ok&game=rdr2", 520, 900),
    "m-home-shelf": ("?still&ok&game=rdr2&layout=shelf", 520, 900),
    "m-home-live": ("?still&demo&game=rdr2", 520, 900),
    "m-home-cards": ("?still&demo&game=rdr2&scroll=760", 520, 900),
    "m-look": ("?still&ok&view=look&game=rdr2", 520, 2400),
    "m-library": ("?still&ok&library", 520, 900),
    "m-guide": ("?still&view=guide&step=2", 520, 1500),
    "m-screen": ("?still&ok&demo&view=screen", 520, 900),
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
