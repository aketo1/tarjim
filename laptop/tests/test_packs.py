"""Game files: export, import, the bundled library, and the rules for merging into a profile."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from tarjim import packs, paths
from tarjim.app import server
from tarjim.translate import Cache, load_profile, save_profile

REAL_REPO = paths.REPO


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """Profiles, library, cache and config in a temp folder: the user's files are never touched."""
    repo = tmp_path / "repo"
    (repo / "profiles").mkdir(parents=True)
    (repo / "packs").mkdir()
    (repo / "profiles" / "default.yaml").write_text("title: Any game\nglossary: {}\n", encoding="utf-8")
    home = tmp_path / "home"
    monkeypatch.setattr(paths, "HOME_DIR", home)
    monkeypatch.setattr(paths, "CONFIG_FILE", home / "config.json")
    monkeypatch.setattr(paths, "REPO", repo)
    return repo


def game(**extra):
    base = {"tarjim": "tarjim-game", "version": 1, "id": "wild-west", "title": "Wild West",
            "names": [{"en": "Hank", "ar": "هانك"}, {"en": "Rosa", "ar": "روزا", "f": True},
                      {"en": "Dusty Gulch", "ar": "داستي غولتش", "was": ["داستي جولتش"]}]}
    base.update(extra)
    return base


def test_a_file_is_checked_and_cleaned():
    pack = packs.parse(game(names=[{"en": " Hank ", "ar": "هانك"}, {"en": "Hank", "ar": "مكرر"}, {"en": "", "ar": "x"},
                                   "junk", {"en": "Rosa", "ar": "روزا", "f": 1, "was": ["روزا", "روزه"]}],
                            fixes=[{"en": "Howdy.", "ar": "هلا."}, {"en": "Howdy.", "ar": "مكرر"}],
                            settings={"settle_ms": 9999, "region": {"left": -1, "top": 0.7, "right": 2, "bottom": 1}}))
    assert pack["names"] == [{"en": "Hank", "ar": "هانك"}, {"en": "Rosa", "ar": "روزا", "f": True, "was": ["روزه"]}]
    assert pack["fixes"] == [{"en": "Howdy.", "ar": "هلا."}]
    assert pack["settings"]["settle_ms"] == 600
    r = pack["settings"]["region"]
    assert 0 <= r["left"] < r["right"] <= 1
    for bad in ({}, {"tarjim": "other"}, game(version=99), game(id="", title="")):
        with pytest.raises(packs.PackError):
            packs.parse(bad)
    with pytest.raises(packs.PackError):
        packs.load("not json")


def test_importing_adds_new_names_and_keeps_the_players_own(sandbox):
    save_profile("wild-west", {"title": "Wild West", "glossary": {"Hank": "هنك", "Dusty Gulch": "داستي جولتش", "Mine": "منجم"}})
    result = packs.merge(packs.parse(game()))
    assert (result["created"], result["added"], result["updated"], result["kept"]) == (False, 1, 1, 1)
    prof = load_profile("wild-west")
    assert prof["glossary"]["Hank"] == "هنك"  # the player's spelling stays
    assert prof["glossary"]["Dusty Gulch"] == "داستي غولتش"  # an old spelling nobody changed is updated
    assert prof["glossary"]["Rosa"] == "روزا" and prof["female"] == ["Rosa"]
    assert prof["glossary"]["Mine"] == "منجم"  # names the file does not have are not removed


def test_a_new_game_takes_the_files_settings_and_line_fixes(sandbox):
    pack = packs.parse(game(fixes=[{"en": "Howdy,  partner.", "ar": "هلا يا  شريكي."}],
                            settings={"settle_ms": 280, "region": {"left": 0.1, "top": 0.6, "right": 0.9, "bottom": 1}}))
    result = packs.merge(pack)
    assert result["created"] and result["added"] == 3 and result["fixes"] == 1
    prof = load_profile("wild-west")
    assert prof["settle_ms"] == 280 and prof["region"]["top"] == 0.6
    cache = Cache()
    try:
        assert cache.get_fix("wild-west", "Howdy, partner.") == "هلا يا شريكي."
        cache.put_fix("wild-west", "Howdy, partner.", "كلامي أنا")
    finally:
        cache.close()
    packs.merge(pack)  # importing again never overwrites the player's own wording
    cache = Cache()
    try:
        assert cache.get_fix("wild-west", "Howdy, partner.") == "كلامي أنا"
    finally:
        cache.close()


def test_export_then_import_on_another_machine_gives_the_same_game(sandbox, tmp_path, monkeypatch):
    save_profile("wild-west", {"title": "Wild West", "settle_ms": 40, "glossary": {"Hank": "هانك", "Rosa": "روزا"},
                               "female": ["Rosa"], "region": {"left": 0.1, "top": 0.65, "right": 0.9, "bottom": 1}})
    cache = Cache()
    try:
        cache.put_fix("wild-west", "Howdy.", "هلا.")
    finally:
        cache.close()
    out = packs.export("wild-west")
    text = json.dumps(out, ensure_ascii=False)
    assert packs.file_name(out) == "Wild West - tarjim.json"

    # Another laptop: empty profiles and cache.
    other = tmp_path / "other"
    (other / "profiles").mkdir(parents=True)
    monkeypatch.setattr(paths, "REPO", other)
    monkeypatch.setattr(paths, "HOME_DIR", tmp_path / "other-home")
    result = packs.merge(packs.load(text))
    assert result["created"] and result["added"] == 2 and result["fixes"] == 1
    prof = load_profile("wild-west")
    assert prof["glossary"] == {"Hank": "هانك", "Rosa": "روزا"} and prof["female"] == ["Rosa"]
    assert prof["settle_ms"] == 40 and prof["region"]["top"] == 0.65


def test_the_library_shows_what_adding_would_change(sandbox):
    (sandbox / "packs" / "wild-west.json").write_text(json.dumps(game(title_ar="الغرب", note="ملاحظة")), encoding="utf-8")
    (sandbox / "packs" / "broken.json").write_text("{", encoding="utf-8")
    [item] = packs.library_view()
    assert item["id"] == "wild-west" and item["title_ar"] == "الغرب" and item["installed"] is False and item["new"] == 3
    packs.merge(packs.library_pack("wild-west"))
    [item] = packs.library_view()
    assert item["installed"] is True and item["new"] == 0
    with pytest.raises(packs.PackError):
        packs.library_pack("nothing")


def test_the_bundled_library_is_valid_and_holds_no_game_lines():
    files = sorted((REAL_REPO / "packs").glob("*.json"))
    assert len(files) >= 20
    ids = set()
    for path in files:
        raw = json.loads(path.read_text(encoding="utf-8"))
        pack = packs.parse(raw)
        assert pack["id"] == path.stem and pack["id"] not in ids
        ids.add(pack["id"])
        assert pack["title_ar"] and len(pack["names"]) >= 15, path.name
        assert raw.get("fixes", []) == [], path.name  # names only: never lines from a game
        assert len(pack["names"]) == len(raw["names"]), f"{path.name}: duplicate or broken rows"
        for row in pack["names"]:
            assert not any("a" <= c.lower() <= "z" for c in row["ar"]), f"{path.name}: {row}"


def test_http_routes(sandbox, monkeypatch):
    (sandbox / "packs" / "wild-west.json").write_text(json.dumps(game()), encoding="utf-8")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = httpd.server_address[1]
    monkeypatch.setattr(server, "PORT", port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    def call(path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"},
                                     method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    try:
        status, view = call("/api/packs")
        assert status == 200 and view["packs"][0]["id"] == "wild-west"
        status, result = call("/api/packs/add", {"id": "wild-west"})
        assert status == 200 and result["created"] and "wild-west" in [p["name"] for p in result["profiles"]]
        status, out = call("/api/pack/export?name=wild-west")
        assert status == 200 and out["file"].endswith(".json") and len(out["pack"]["names"]) == 3
        out["pack"]["names"].append({"en": "Sheriff Cole", "ar": "الشريف كول"})
        out["pack"]["fixes"] = [{"en": f"Line {i}.", "ar": f"سطر {i}."} for i in range(3000)]  # a big file
        status, result = call("/api/pack/import", {"pack": out["pack"]})
        assert status == 200 and result["added"] == 1 and result["fixes"] == 3000
        status, err = call("/api/pack/import", {"pack": {"tarjim": "nope"}})
        assert status >= 400 and "ترجِم" in err["error"]
    finally:
        httpd.shutdown()
