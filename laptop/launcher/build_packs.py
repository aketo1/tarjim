"""Build the game library: packs/source/*.txt  ->  packs/<id>.json (and the phone app's copy).

The source files are easy to edit by hand:

    Files are read in name order (1-red-dead.txt, 2-gta.txt, ...) and the library lists the
    games in that order, so the numbers in the file names decide it.

    [game rdr2]                       a game: its file name and the profile it fills
    title: Red Dead Redemption 2
    title_ar: ريد ديد ريدمبشن 2
    series: Red Dead
    year: 2018
    settle: 30                        optional: ms a line must stay unchanged (typewriter text)
    note: one line shown in the library

    Arthur Morgan = آرثر مورغان
    Sadie = سايدي ♀ ~ سيدي            ♀ a woman's name; ~ a spelling older files used
    Kiryu = كيريو @ yakuza0 yakuza3   @ the games of this file it belongs to (default: the
                                        game above it; under [shared], @ is required; @all = every game)

Names only: never lines from a game.

    python launcher/build_packs.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SOURCE = REPO / "packs" / "source"
OUT = REPO / "packs"
PHONE = REPO.parent / "tarjim-android" / "tarjim-phone" / "android" / "app" / "src" / "main" / "assets" / "packs"

META = {"title": "title", "title_ar": "title_ar", "series": "series", "year": "year", "note": "note",
        "settle": "settle_ms"}


class SourceError(Exception):
    pass


def parse_file(path: Path) -> dict[str, dict]:
    games: dict[str, dict] = {}
    current: str | None = None
    shared = False
    for no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        where = f"{path.name}:{no}"
        m = re.fullmatch(r"\[game ([a-z0-9][a-z0-9-]{0,40})\]", line)
        if m:
            current, shared = m.group(1), False
            if current in games:
                raise SourceError(f"{where}: game {current} defined twice")
            games[current] = {"id": current, "names": [], "_meta_open": True}
            continue
        if line == "[shared]":
            current, shared = None, True
            continue
        m = re.fullmatch(r"([a-z_]+):\s*(.*)", line)
        if m and current and games[current].get("_meta_open") and m.group(1) in META:
            value = m.group(2).strip()
            games[current][META[m.group(1)]] = float(value) if m.group(1) == "settle" else value
            continue
        if "=" not in line:
            raise SourceError(f"{where}: not a name line: {line}")
        en, rest = (s.strip() for s in line.split("=", 1))
        tags = None
        if "@" in rest:
            rest, tag_text = rest.split("@", 1)
            tags = tag_text.split()
        parts = [p.strip() for p in rest.split("~")]
        ar, was = parts[0], [p for p in parts[1:] if p]
        female = "♀" in ar
        ar = re.sub(r"\s+", " ", ar.replace("♀", "")).strip()
        if not en or not ar:
            raise SourceError(f"{where}: empty name")
        if re.search(r"[A-Za-z]", ar):
            raise SourceError(f"{where}: Latin letters in the Arabic: {ar}")
        row = {"en": en, "ar": ar}
        if female:
            row["f"] = True
        if was:
            row["was"] = was
        if tags is None:
            if shared or current is None:
                raise SourceError(f"{where}: a shared name needs @ and the games it belongs to")
            targets = [current]
        elif tags == ["all"]:
            targets = None  # resolved at the end, when every game of the file is known
        else:
            targets = tags
        if current:
            games[current]["_meta_open"] = False
        games.setdefault("_rows", {"id": "_rows", "names": []})["names"].append((targets, row, where))
    rows = games.pop("_rows", {"names": []})["names"]
    for targets, row, where in rows:
        for gid in (targets if targets is not None else list(games)):
            if gid not in games:
                raise SourceError(f"{where}: unknown game {gid}")
            if any(r["en"] == row["en"] for r in games[gid]["names"]):
                raise SourceError(f"{where}: {row['en']} twice in {gid}")
            games[gid]["names"].append(row)
    for game in games.values():
        game.pop("_meta_open", None)
        if not game.get("title") or not game.get("title_ar"):
            raise SourceError(f"{path.name}: game {game['id']} needs title and title_ar")
    return games


def render(game: dict) -> str:
    """One name per line, so a change to a list reads well in a diff."""
    head = {"tarjim": "tarjim-game", "version": 1, "id": game["id"], "title": game["title"],
            "title_ar": game["title_ar"]}
    for key in ("series", "year", "note", "order"):
        if game.get(key):
            head[key] = game[key]
    lines = ["{"]
    lines += [f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}," for k, v in head.items()]
    if "settle_ms" in game:
        lines.append(f'  "settings": {{"settle_ms": {game["settle_ms"]:g}}},')
    lines.append('  "names": [')
    rows = [f"    {json.dumps(r, ensure_ascii=False)}" for r in game["names"]]
    lines.append(",\n".join(rows))
    lines.append("  ]")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> int:
    games: dict[str, dict] = {}
    for path in sorted(SOURCE.glob("*.txt")):  # file order, then order in the file: how the library lists them
        for gid, game in parse_file(path).items():
            if gid in games:
                raise SourceError(f"game {gid} is in two source files")
            game["order"] = len(games) + 1
            games[gid] = game
    OUT.mkdir(exist_ok=True)
    targets = [OUT] + ([PHONE] if PHONE.parent.exists() else [])
    for target in targets:
        target.mkdir(exist_ok=True)
        for old in target.glob("*.json"):
            if old.stem not in games:
                old.unlink()
        for gid, game in games.items():
            (target / f"{gid}.json").write_text(render(game), encoding="utf-8", newline="\n")
    total = sum(len(g["names"]) for g in games.values())
    print(f"{len(games)} games, {total} names -> {', '.join(str(t) for t in targets)}")
    for gid, game in sorted(games.items()):
        print(f"  {gid:18} {len(game['names']):4}  {game['title']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SourceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
