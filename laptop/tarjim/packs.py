"""Game files: one game's names, the player's own line fixes and where its subtitles sit,
in a JSON file anyone can pass on. The library that comes with the program (packs/*.json)
uses the same format, and so does the phone app, so a file made on one opens on the other.

    {"tarjim": "tarjim-game", "version": 1, "id": "rdr2", "title": "Red Dead Redemption 2",
     "title_ar": "...", "names": [{"en": "Sadie", "ar": "سايدي", "f": true, "was": ["سيدي"]}],
     "fixes": [{"en": "...", "ar": "..."}], "settings": {"settle_ms": 30, "region": {...}}}

`f` marks a woman's name (her verbs come out female); `was` lists spellings an older
version of the file used, which are updated when nobody changed them by hand.
Bundled files carry names only: never lines from a game.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path

from . import paths

KIND = "tarjim-game"
VERSION = 1
MAX_NAMES = 3000
MAX_FIXES = 20000
NAME_LEN = 60
LINE_LEN = 400


class PackError(ValueError):
    """A file that is not a usable game file; the message is for the user (Arabic)."""


def library_dir() -> Path:
    return paths.REPO / "packs"


def profiles_dir() -> Path:
    return paths.REPO / "profiles"


def slug(text: str) -> str:
    s = "".join(c if c.isascii() and c.isalnum() else "-" for c in str(text).lower())
    s = "-".join(p for p in s.split("-") if p)[:30]
    return s if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,40}", s or "") else ""


def _text(value, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def parse(obj) -> dict:
    """Check a game file and return a clean copy. Raises PackError."""
    if not isinstance(obj, dict) or obj.get("tarjim") != KIND:
        raise PackError("هذا مو ملف لعبة من ترجِم.")
    try:
        version = int(obj.get("version", 1))
    except (TypeError, ValueError):
        version = 1
    if version > VERSION:
        raise PackError("الملف من نسخة أحدث من ترجِم. حدّث البرنامج وجرّب مرة ثانية.")
    title = _text(obj.get("title"), 60)
    gid = slug(obj.get("id") or "") or slug(title)
    if not gid:
        raise PackError("الملف ما فيه اسم لعبة واضح.")

    names, seen = [], set()
    for row in obj.get("names") or []:
        if not isinstance(row, dict):
            continue
        en, ar = _text(row.get("en"), NAME_LEN), _text(row.get("ar"), NAME_LEN)
        if not en or not ar or en in seen:
            continue
        seen.add(en)
        item = {"en": en, "ar": ar}
        if row.get("f"):
            item["f"] = True
        was = [w for w in (_text(v, NAME_LEN) for v in (row.get("was") or [])[:5]) if w and w != ar]
        if was:
            item["was"] = was
        names.append(item)
        if len(names) >= MAX_NAMES:
            break

    fixes, seen = [], set()
    for row in obj.get("fixes") or []:
        if not isinstance(row, dict):
            continue
        en, ar = _text(row.get("en"), LINE_LEN), _text(row.get("ar"), LINE_LEN)
        if en and ar and en not in seen:
            seen.add(en)
            fixes.append({"en": en, "ar": ar})
            if len(fixes) >= MAX_FIXES:
                break

    settings, raw = {}, obj.get("settings") if isinstance(obj.get("settings"), dict) else {}
    try:
        if "settle_ms" in raw:
            settings["settle_ms"] = max(0.0, min(600.0, float(raw["settle_ms"])))
        if "read_scale" in raw:
            settings["read_scale"] = max(0.5, min(2.5, float(raw["read_scale"])))
        if isinstance(raw.get("region"), dict):
            from . import settings as settings_mod

            settings["region"] = settings_mod.region({"region": raw["region"]})
    except (TypeError, ValueError):
        pass

    out = {"tarjim": KIND, "version": VERSION, "id": gid, "title": title or gid, "names": names}
    for key, limit in (("title_ar", 60), ("series", 40), ("note", 300), ("made", 20), ("year", 8)):
        if obj.get(key):
            out[key] = _text(obj[key], limit)
    if isinstance(obj.get("order"), int) and not isinstance(obj.get("order"), bool):
        out["order"] = obj["order"]
    out["fixes"] = fixes
    out["settings"] = settings
    return out


def load(text: str | bytes) -> dict:
    try:
        obj = json.loads(text)
    except (ValueError, UnicodeDecodeError) as exc:
        raise PackError("الملف تالف أو مو ملف لعبة من ترجِم.") from exc
    return parse(obj)


# -- the library ------------------------------------------------------------------


def library() -> list[dict]:
    out = []
    for path in sorted(library_dir().glob("*.json")):
        try:
            out.append(load(path.read_text(encoding="utf-8")))
        except (OSError, PackError):
            continue  # a broken file is left out, not fatal
    return out


def library_pack(gid: str) -> dict:
    for pack in library():
        if pack["id"] == gid:
            return pack
    raise PackError("هذي اللعبة مو موجودة في المكتبة.")


def _profile(name: str) -> dict | None:
    from .translate import load_profile

    if not (profiles_dir() / f"{name}.yaml").exists():
        return None
    try:
        return load_profile(name)
    except Exception:
        return None


def _pending(pack: dict, prof: dict | None) -> int:
    """How many names in the file would change this profile."""
    if prof is None:
        return len(pack["names"])
    have = {str(k): str(v) for k, v in (prof.get("glossary") or {}).items()}
    return sum(1 for n in pack["names"] if n["en"] not in have or have[n["en"]] in n.get("was", ()))


def library_view() -> list[dict]:
    """The library as the page shows it: the player's own games first, then the library's order."""
    items = []
    for pack in sorted(library(), key=lambda p: (p.get("order", 10_000), p["title"])):
        prof = _profile(pack["id"])
        items.append({
            "id": pack["id"], "title": pack["title"], "title_ar": pack.get("title_ar", ""),
            "series": pack.get("series", ""), "year": pack.get("year", ""), "note": pack.get("note", ""),
            "names": len(pack["names"]), "women": sum(1 for n in pack["names"] if n.get("f")),
            "installed": prof is not None, "new": _pending(pack, prof),
        })
    return sorted(items, key=lambda item: not item["installed"])  # stable: keeps the order within each part


# -- into and out of a profile ----------------------------------------------------------


def merge(pack: dict, into: str | None = None) -> dict:
    """Add a game file to a profile (made if it does not exist).

    New names are added; a name the player already has keeps the player's spelling,
    unless that spelling is one the file says an older version used (`was`). The
    player's own line fixes are kept too; only lines without one are added.
    """
    from .translate import Cache, normalize_arabic, normalize_english, save_profile

    name = slug(into or "") or pack["id"]
    prof = _profile(name)
    created = prof is None
    if created:
        prof = {"title": pack["title"], "style": "msa", "settle_ms": 60, "glossary": {}}
        for key in ("settle_ms", "read_scale", "region"):
            if key in pack["settings"]:
                prof[key] = pack["settings"][key]
    glossary = {str(k): str(v) for k, v in (prof.get("glossary") or {}).items()}
    female = [str(n) for n in (prof.get("female") or [])]
    added = updated = kept = 0
    for row in pack["names"]:
        en, ar = row["en"], row["ar"]
        current = glossary.get(en)
        if current is None:
            glossary[en] = ar
            added += 1
        elif current != ar:
            if current not in row.get("was", ()):
                kept += 1
                continue
            glossary[en] = ar
            updated += 1
        if row.get("f") and en not in female:
            female.append(en)
    prof["glossary"] = glossary
    prof["female"] = female
    save_profile(name, prof)

    fixes = 0
    if pack["fixes"]:
        cache = Cache()
        try:
            fixes = cache.add_fixes(name, [(normalize_english(r["en"]), normalize_arabic(r["ar"])) for r in pack["fixes"]])
        finally:
            cache.close()
    return {"name": name, "title": str(prof.get("title") or name), "created": created,
            "added": added, "updated": updated, "kept": kept, "fixes": fixes}


def export(name: str) -> dict:
    """A profile as a game file: its names, the player's line fixes, and its reading area and timing."""
    from . import settings as settings_mod
    from .translate import Cache, load_profile

    prof = load_profile(name)
    female = {str(n) for n in (prof.get("female") or [])}
    names = []
    for en, ar in (prof.get("glossary") or {}).items():
        item = {"en": str(en), "ar": str(ar)}
        if str(en) in female:
            item["f"] = True
        names.append(item)
    cache = Cache()
    try:
        fixes = [{"en": en, "ar": ar} for en, ar in cache.fixes(name)]
    finally:
        cache.close()
    settings = {"settle_ms": float(prof.get("settle_ms", 60)), "read_scale": float(prof.get("read_scale", 1.0))}
    if prof.get("region"):
        settings["region"] = settings_mod.region(prof)
    title = str(prof.get("title") or name)
    gid = name if name != "default" else (slug(title) or "game")
    return {"tarjim": KIND, "version": VERSION, "id": gid, "title": title,
            "made": _dt.date.today().isoformat(), "names": names, "fixes": fixes, "settings": settings}


def file_name(pack: dict) -> str:
    """A file name that works on Windows and Android: the game's title, then the program's name."""
    base = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", pack.get("title") or pack["id"]).strip(" .")[:50] or pack["id"]
    return f"{base} - tarjim.json"
