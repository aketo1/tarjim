"""Copy the interface to the standalone phone app: python launcher/sync_phone_web.py

The laptop program and the phone app show the same page (tarjim/app/web). The phone app
keeps its own copy in android/app/src/main/assets/web of the tarjim-phone repo, which sits
next to this one. Run this after changing the page, then build the phone app.
"""

from __future__ import annotations

import filecmp
import shutil
import sys
from pathlib import Path

LAPTOP = Path(__file__).resolve().parents[1]
WEB = LAPTOP / "tarjim" / "app" / "web"
PHONE_WEB = LAPTOP.parent.parent / "tarjim-android" / "tarjim-phone" / "android" / "app" / "src" / "main" / "assets" / "web"
FILES = ("index.html", "app.css", "app.js", "glass.js", "xbox.js", "xCloudPlayer.min.js", "icon.png")


def main() -> int:
    if not PHONE_WEB.parent.exists():
        print(f"no phone app at {PHONE_WEB.parent}")
        return 1
    PHONE_WEB.mkdir(exist_ok=True)
    changed = 0
    for name in FILES:
        src, dst = WEB / name, PHONE_WEB / name
        if dst.exists() and filecmp.cmp(src, dst, shallow=False):
            continue
        shutil.copy2(src, dst)
        changed += 1
        print("copied", name)
    print(f"{changed} file(s) changed in {PHONE_WEB}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
