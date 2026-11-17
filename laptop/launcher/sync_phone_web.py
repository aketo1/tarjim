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
FILES = ("index.html", "app.css", "app.js", "look.js", "art.js", "xbox.js", "xCloudPlayer.min.js", "icon.png")
FOLDERS = ("art",)  # the games' pictures (launcher/fetch_art.py)
GONE = ("glass.js",)  # files of an older page that the phone app must not keep


def wanted() -> list[str]:
    names = list(FILES)
    for folder in FOLDERS:
        names += sorted(p.relative_to(WEB).as_posix() for p in (WEB / folder).rglob("*") if p.is_file())
    return names


def main() -> int:
    if not PHONE_WEB.parent.exists():
        print(f"no phone app at {PHONE_WEB.parent}")
        return 1
    PHONE_WEB.mkdir(exist_ok=True)
    changed = 0
    names = wanted()
    for name in names:
        src, dst = WEB / name, PHONE_WEB / name
        if dst.exists() and filecmp.cmp(src, dst, shallow=False):
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        changed += 1
        print("copied", name)
    for folder in FOLDERS:  # a picture taken out of the page leaves the phone app too
        for p in sorted((PHONE_WEB / folder).rglob("*")) if (PHONE_WEB / folder).exists() else []:
            if p.is_file() and p.relative_to(PHONE_WEB).as_posix() not in names:
                p.unlink()
                changed += 1
                print("removed", p.relative_to(PHONE_WEB).as_posix())
    for name in GONE:
        if (PHONE_WEB / name).exists():
            (PHONE_WEB / name).unlink()
            changed += 1
            print("removed", name)
    print(f"{changed} file(s) changed in {PHONE_WEB}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
