"""Where things live: the repo, the bundled tools, the user's private folder."""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / ".tools"
DOCS = REPO / "docs"
HOME_DIR = Path.home() / ".tarjim"
CONFIG_FILE = HOME_DIR / "config.json"
TV_STATE_FILE = HOME_DIR / "tv-state.json"
APK = REPO / "tv-app" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"

_EXE = ".exe" if sys.platform == "win32" else ""


def adb_path() -> Path | None:
    bundled = TOOLS / "platform-tools" / f"adb{_EXE}"
    if bundled.exists():
        return bundled
    found = shutil.which("adb")
    return Path(found) if found else None


def jdk_home() -> Path | None:
    bundled = TOOLS / "jdk17"
    if (bundled / "bin" / f"java{_EXE}").exists():
        return bundled
    env = os.environ.get("JAVA_HOME")
    if env and (Path(env) / "bin" / f"java{_EXE}").exists():
        return Path(env)
    return None


def android_sdk() -> Path | None:
    bundled = TOOLS / "android-sdk"
    if bundled.exists():
        return bundled
    for name in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        env = os.environ.get(name)
        if env and Path(env).exists():
            return Path(env)
    return None


def ensure_home() -> Path:
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        HOME_DIR.chmod(stat.S_IRWXU)
    # On Windows the folder sits inside the user profile, whose ACL already
    # limits access to the user, SYSTEM and Administrators.
    return HOME_DIR


def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {}


def save_config(cfg: dict) -> None:
    ensure_home()
    write_private(CONFIG_FILE, json.dumps(cfg, ensure_ascii=False, indent=2))


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if sys.platform != "win32":
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
