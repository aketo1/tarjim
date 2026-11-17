"""Translation: one interface, local engines, an SQLite cache, Arabic clean-up."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Protocol

from . import paths

MODELS_DIR = paths.REPO / "models"
CACHE_FILE = paths.HOME_DIR / "translations.sqlite"


class TranslateError(Exception):
    pass


class Translator(Protocol):
    name: str

    def translate(self, text: str, context: list[tuple[str, str]] | None = None) -> str: ...


# -- text clean-up ---------------------------------------------------------------

_WS = re.compile(r"\s+")


def normalize_english(text: str) -> str:
    """Cache key form: one spacing, straight quotes; case is kept (it carries meaning)."""
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return _WS.sub(" ", text).strip()


def normalize_arabic(text: str) -> str:
    """Arabic punctuation, no stray Latin quotes, no doubled spaces or marks."""
    text = text.replace("\u200f", "").replace("\u200e", "")
    # Short vowels make subtitles slow to read; keep only tanween and shadda.
    text = re.sub("[\u064e\u064f\u0650\u0652\u0670]", "", text)
    text = _WS.sub(" ", text).strip()
    text = text.strip('"').strip("'").strip("«»").strip()
    # The models like to wrap names in brackets: "يا سيد (مورغان)".
    text = re.sub(r"\(([^()\s]+(?:\s[^()\s]+)?)\)", lambda m: m.group(1), text)
    text = re.sub(r"(?<=[؀-ۿ])\s*,", "،", text)
    text = re.sub(r"(?<=[؀-ۿ])\s*\?", "؟", text)
    text = re.sub(r"(?<=[؀-ۿ])\s*;", "؛", text)
    text = re.sub(r"\s+([،؛؟.!:])", r"\1", text)
    text = re.sub(r"([،؛؟!])\1+", r"\1", text)
    text = re.sub(r"\.{4,}", "...", text)
    return text.strip()


# -- cache -------------------------------------------------------------------------


class Cache:
    """Keyed by profile, normalised English, engine and style. Thread-safe."""

    def __init__(self, path: Path | str | None = None) -> None:
        # Looked up now, not at import, so a test that moves the home folder moves the cache too.
        self.path = Path(path) if path else paths.HOME_DIR / CACHE_FILE.name
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS tr (profile TEXT, en TEXT, engine TEXT, style TEXT, ar TEXT, ts REAL,"
            " PRIMARY KEY (profile, en, engine, style))"
        )
        # A line the user corrected by hand always wins over the engine.
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS fix (profile TEXT, en TEXT, ar TEXT, ts REAL, PRIMARY KEY (profile, en))"
        )
        # How the engine writes a glossary name on its own (see NameGuard).
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS names (engine TEXT, en TEXT, mode TEXT, variant TEXT,"
            " PRIMARY KEY (engine, en))"
        )
        self._db.commit()

    def get_fix(self, profile: str, en: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT ar FROM fix WHERE profile=? AND en=?", (profile, en)).fetchone()
        return row[0] if row else None

    def put_fix(self, profile: str, en: str, ar: str | None) -> None:
        """Store the user's own Arabic for a line; None or empty removes it."""
        with self._lock:
            if ar:
                self._db.execute("INSERT OR REPLACE INTO fix VALUES (?,?,?,?)", (profile, en, ar, time.time()))
            else:
                self._db.execute("DELETE FROM fix WHERE profile=? AND en=?", (profile, en))
            self._db.commit()

    def add_fixes(self, profile: str, rows: list[tuple[str, str]]) -> int:
        """Many lines at once, in one write; a line that already has the user's wording keeps it.
        Returns how many were added."""
        with self._lock:
            before = self._db.total_changes
            self._db.executemany("INSERT OR IGNORE INTO fix VALUES (?,?,?,?)",
                                 [(profile, en, ar, time.time()) for en, ar in rows if en and ar])
            self._db.commit()
            return self._db.total_changes - before

    def fixes(self, profile: str) -> list[tuple[str, str]]:
        """Every line the user rewrote for this game, oldest first."""
        with self._lock:
            rows = self._db.execute("SELECT en, ar FROM fix WHERE profile=? ORDER BY ts", (profile,)).fetchall()
        return [(en, ar) for en, ar in rows]

    def get_name(self, engine: str, en: str) -> tuple[str, str] | None:
        with self._lock:
            row = self._db.execute("SELECT mode, variant FROM names WHERE engine=? AND en=?", (engine, en)).fetchone()
        return (row[0], row[1] or "") if row else None

    def put_name(self, engine: str, en: str, mode: str, variant: str) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO names VALUES (?,?,?,?)", (engine, en, mode, variant))
            self._db.commit()

    def get(self, profile: str, en: str, engine: str, style: str) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT ar FROM tr WHERE profile=? AND en=? AND engine=? AND style=?", (profile, en, engine, style)
            ).fetchone()
        return row[0] if row else None

    def put(self, profile: str, en: str, engine: str, style: str, ar: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO tr VALUES (?,?,?,?,?,?)", (profile, en, engine, style, ar, time.time())
            )
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()


# -- sentences ---------------------------------------------------------------------

_SENT = re.compile(r"(?<=[.!?…])[\"')\]]*\s+(?=[\"'(\[]*[A-Z0-9])")
_ABBREV = re.compile(r"(?:^|\s)(?:Mr|Mrs|Ms|Dr|St|Jr|Sr|Mt|Lt|Sgt|Capt|Col|Gen|No|vs)\.$")
_END_PUNCT = {".": ".", "!": "!", "?": "؟", "…": "…"}


def split_sentences(text: str) -> list[str]:
    """NMT models tend to drop everything after the first sentence, so feed them one at a time."""
    parts: list[str] = []
    for piece in (p.strip() for p in _SENT.split(text)):
        if not piece:
            continue
        if parts and _ABBREV.search(parts[-1]):
            parts[-1] = f"{parts[-1]} {piece}"  # "Mr. Smith" is not two sentences
        else:
            parts.append(piece)
    return parts or [text]


def join_sentences(sources: list[str], translations: list[str]) -> str:
    """Join per-sentence translations, restoring end punctuation the model dropped."""
    out = []
    for en, ar in zip(sources, translations):
        ar = ar.strip()
        if not ar:
            continue
        last = en.rstrip("\"')]")[-1:] if en else ""
        if last in _END_PUNCT and ar[-1] not in ".!؟?…،":
            ar += "..." if en.rstrip("\"')]").endswith("...") else _END_PUNCT[last]
        out.append(ar)
    return " ".join(out)


# -- local engines -----------------------------------------------------------------


def _threads() -> int:
    import os

    # Few threads on purpose: during play the video decoder and the frame loop
    # need the other cores, and oversubscription made translation 4x slower.
    return max(2, min(4, (os.cpu_count() or 4) // 3))


class NllbTranslator:
    """facebook/nllb-200-distilled-600M converted to CTranslate2 int8 (eng_Latn to arb_Arab)."""

    name = "nllb-600m"

    def __init__(self, model_dir: Path | None = None) -> None:
        import ctranslate2
        import sentencepiece as spm

        d = model_dir or MODELS_DIR / "nllb-200-distilled-600M-ct2-int8"
        if not (d / "model.bin").exists():
            raise TranslateError(f"translation model missing: {d}")
        self._sp = spm.SentencePieceProcessor(model_file=str(d / "sentencepiece.bpe.model"))
        self._tr = ctranslate2.Translator(str(d), device="cpu", compute_type="int8", intra_threads=_threads())

    def translate(self, text: str, context: list[tuple[str, str]] | None = None) -> str:
        return self.translate_many([text])[0]

    def translate_many(self, texts: list[str]) -> list[str]:
        """Several texts in one batch: much faster per text than one call each."""
        parts = [split_sentences(t) for t in texts]
        flat = [p for ps in parts for p in ps]
        src = [["eng_Latn"] + self._sp.encode(p, out_type=str) + ["</s>"] for p in flat]
        res = self._tr.translate_batch(
            src, target_prefix=[["arb_Arab"]] * len(src), beam_size=2, max_decoding_length=128,
            repetition_penalty=1.1, max_batch_size=16,
        )
        # hypotheses[0][0] is the language token
        return _rejoin(parts, [self._sp.decode(r.hypotheses[0][1:]) for r in res])


class OpusTranslator:
    """Helsinki-NLP/opus-mt-tc-big-en-ar converted to CTranslate2."""

    name = "opus-big"

    def __init__(self, model_dir: Path | None = None) -> None:
        import ctranslate2
        import sentencepiece as spm

        d = model_dir or MODELS_DIR / "opus-mt-tc-big-en-ar-ct2"
        if not (d / "model.bin").exists():
            raise TranslateError(f"translation model missing: {d}")
        self._src = spm.SentencePieceProcessor(model_file=str(d / "source.spm"))
        self._tgt = spm.SentencePieceProcessor(model_file=str(d / "target.spm"))
        self._tr = ctranslate2.Translator(str(d), device="cpu", compute_type="int8", intra_threads=_threads())

    def translate(self, text: str, context: list[tuple[str, str]] | None = None) -> str:
        return self.translate_many([text])[0]

    def translate_many(self, texts: list[str]) -> list[str]:
        """Several texts in one batch: much faster per text than one call each."""
        parts = [split_sentences(t) for t in texts]
        flat = [p for ps in parts for p in ps]
        src = [[">>ara<<"] + self._src.encode(p, out_type=str) + ["</s>"] for p in flat]
        res = self._tr.translate_batch(src, beam_size=2, max_decoding_length=128, repetition_penalty=1.1,
                                       max_batch_size=16)
        return _rejoin(parts, [self._tgt.decode(r.hypotheses[0]) for r in res])


def _rejoin(parts: list[list[str]], flat_out: list[str]) -> list[str]:
    """Split a flat list of sentence translations back into one string per input text."""
    out, i = [], 0
    for ps in parts:
        out.append(join_sentences(ps, flat_out[i:i + len(ps)]))
        i += len(ps)
    return out


ENGINES = {"nllb-600m": NllbTranslator, "opus-big": OpusTranslator}
LOCAL_DEFAULT = "opus-big"


def make_engine(name: str) -> Translator:
    if name not in ENGINES:
        raise TranslateError(f"unknown engine {name!r}; choose from {', '.join(ENGINES)}")
    return ENGINES[name]()


def load_profile(name: str) -> dict:
    """profiles/<name>.yaml: glossary, style and detection settings for one game."""
    import yaml

    path = paths.REPO / "profiles" / f"{name}.yaml"
    if not path.exists():
        if name == "default":
            return {}
        raise TranslateError(f"no profile file: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise TranslateError(f"profile {name} is not a mapping")
    return data


def default_engine_name() -> str:
    return paths.load_config().get("mt_engine", "opus-big")


# -- glossary ----------------------------------------------------------------------


def apply_glossary(arabic: str, english: str, glossary: dict[str, str]) -> str:
    """Make names consistent: if an English glossary term is in the source and the
    model left it in Latin letters, put the agreed Arabic form in its place."""
    for en, ar in glossary.items():
        if re.search(rf"\b{re.escape(en)}\b", english, flags=re.IGNORECASE):
            arabic = re.sub(rf"\b{re.escape(en)}\b", ar, arabic, flags=re.IGNORECASE)
    return arabic


# -- names ---------------------------------------------------------------------------

# Stand-in names the engine was measured to write the same way in every sentence.
PROXIES = (("Edward", "إدوارد"), ("Harold", "هارولد"), ("Leonard", "ليونارد"), ("Jonathan", "جوناثان"))
PROXIES_FEMALE = (("Victoria", "فيكتوريا"), ("Catherine", "كاثرين"))  # so verbs agree with a woman's name
_PROBES = ("Hello, {}.", "{} is thinking about it.", "I told {} to wait.", "We got {}.")
_AR_EDGE = "()«»\"'.,،؛؟!:… "


def _words(arabic: str) -> set[str]:
    return {w.strip(_AR_EDGE) for w in normalize_arabic(arabic).split()} - {""}


class NameGuard:
    """Keeps glossary names right.

    A small translation model treats some names as words ("Dutch" came out as
    "the Dutch woman" in every measured line) and spells others its own way.
    Each name is tried once in a few plain sentences and filed as:

    - "ok":      the engine already writes the agreed Arabic form;
    - "variant": it always writes one other spelling, which is swapped afterwards;
    - "proxy":   it is unreliable, so the name is replaced in the English by a
                 stand-in name before translating, and swapped back in the Arabic.
    """

    def __init__(self, engine: Translator, cache: Cache) -> None:
        self.engine = engine
        self.cache = cache
        self._proxy_out: dict[str, str] = {}
        self._memo: dict[tuple[str, str], tuple[str, str]] = {}

    def mode(self, en: str, ar: str) -> tuple[str, str]:
        if (en, ar) in self._memo:
            return self._memo[(en, ar)]
        stored = self.cache.get_name(self.engine.name, en)
        if stored is None:
            stored = self._probe(en)
            self.cache.put_name(self.engine.name, en, *stored)
        mode, variant = stored
        if mode == "variant" and variant == ar:
            mode = "ok"
        self._memo[(en, ar)] = (mode, variant)
        return mode, variant

    def _probe(self, en: str) -> tuple[str, str]:
        """The one word the engine writes for this name in every trial sentence, if there is one:
        the word that is in each translation with the name and in none with the stand-in."""
        proxy_en = PROXIES[0][0]
        common: set[str] | None = None
        for probe in _PROBES:
            if probe not in self._proxy_out:
                self._proxy_out[probe] = self.engine.translate(probe.format(proxy_en))
            own = _words(self.engine.translate(probe.format(en))) - _words(self._proxy_out[probe])
            common = own if common is None else common & own
            if not common:
                return "proxy", ""
        return ("variant", common.pop()) if common and len(common) == 1 else ("proxy", "")

    def _decide(self, outs: list[str]) -> tuple[str, str]:
        """The same verdict as `_probe`, from translations made in a batch."""
        common: set[str] | None = None
        for probe, out in zip(_PROBES, outs):
            own = _words(out) - _words(self._proxy_out[probe])
            common = own if common is None else common & own
            if not common:
                return "proxy", ""
        return ("variant", common.pop()) if common and len(common) == 1 else ("proxy", "")

    def prepare(self, names: list[tuple[str, str]], per_batch: int = 4, stop=None) -> None:
        """Try every name not tried before, a few names per batch.

        One batch is several times faster than the same sentences one by one, and a small
        batch keeps a live line that arrives meanwhile from waiting long behind it.
        `stop` (optional) is asked between batches whether to give up.
        """
        if stop is not None and stop():
            return
        many = getattr(self.engine, "translate_many", None)
        todo = [en for en, ar in names if en and (en, ar) not in self._memo
                and self.cache.get_name(self.engine.name, en) is None]
        if many is not None and todo:
            proxy_en = PROXIES[0][0]
            missing = [p for p in _PROBES if p not in self._proxy_out]
            if missing:
                for probe, out in zip(missing, many([p.format(proxy_en) for p in missing])):
                    self._proxy_out[probe] = out
            for i in range(0, len(todo), per_batch):
                if stop is not None and stop():
                    return
                chunk = todo[i:i + per_batch]
                outs = many([p.format(en) for en in chunk for p in _PROBES])
                for j, en in enumerate(chunk):
                    if self.cache.get_name(self.engine.name, en) is None:  # a live line may have tried it meanwhile
                        got = outs[j * len(_PROBES):(j + 1) * len(_PROBES)]
                        self.cache.put_name(self.engine.name, en, *self._decide(got))
        for en, ar in names:
            if stop is not None and stop():
                return
            if en and ar:
                self.mode(en, ar)  # from the cache now; engines without batches try one by one here


def _name_rx(en: str) -> re.Pattern:
    return re.compile(rf"(?<![A-Za-z]){re.escape(en)}(?![A-Za-z])", flags=re.IGNORECASE)


def _literal(text: str) -> str:
    """A regex for this text where straight and curly apostrophes count as the same."""
    return "".join("['’]" if ch in "'’" else re.escape(ch) for ch in text)


def name_pattern(en: str) -> re.Pattern:
    """How a glossary name is found in a line.

    A name that starts with a capital ("Chop", "Families") must appear with that
    capital, or all in capitals ("CHOP"), so the same word in small letters ("chop the
    wood", "our families") is left to the translator. A name written in small letters
    ("van der Linde", "clicker") is found in any case.
    """
    first = next((c for c in en if c.isalpha()), "")
    if first.isupper():
        exact, upper = _literal(en), _literal(en.upper())
        body = exact if exact == upper else f"(?:{exact}|{upper})"
        return re.compile(rf"(?<![A-Za-z]){body}(?![A-Za-z])")
    return re.compile(rf"(?<![A-Za-z]){_literal(en)}(?![A-Za-z])", flags=re.IGNORECASE)


class CachedTranslator:
    """The user's own fix first, then the cache, then the engine; always returns cleaned Arabic."""

    def __init__(self, engine: Translator, cache: Cache, profile: str = "default", style: str = "msa",
                 glossary: dict[str, str] | None = None, female: set[str] | None = None) -> None:
        self.engine = engine
        self.cache = cache
        self.profile = profile
        self.style = style
        self._patterns: list[tuple[str, str, re.Pattern]] = []
        self.glossary = glossary or {}
        self.female = set(female or ())  # glossary names that belong to women
        self.names = NameGuard(engine, cache)
        self.history: list[tuple[str, str]] = []

    @property
    def glossary(self) -> dict[str, str]:
        return self._glossary

    @glossary.setter
    def glossary(self, value: dict[str, str]) -> None:
        # Compiled once per list, longest first ("Mary Beth" before "Mary"): a game list
        # can have hundreds of names, and every line is checked against all of them.
        g = {str(k): str(v) for k, v in (value or {}).items()}
        self._glossary = g
        self._patterns = sorted(((en, ar, name_pattern(en)) for en, ar in g.items() if en and ar),
                                key=lambda t: -len(t[0]))

    def prepare_names(self, stop=None) -> None:
        """Try every glossary name once now, so the first line with a name is not slowed down."""
        self.names.prepare(list(self.glossary.items()), stop=stop)

    def _matched(self, key: str) -> list[tuple[str, str]]:
        """The glossary names in this line, longest first. A name found only inside a longer
        one ("Arthur" inside "Arthur Morgan") is part of that one and does not count."""
        found, masked = [], key
        for en, ar, pattern in self._patterns:
            spans = [m.span() for m in pattern.finditer(masked)]
            if not spans:
                continue
            found.append((en, ar))
            for a, b in spans:
                masked = masked[:a] + "\0" * (b - a) + masked[b:]
        return found

    def _engine_key(self, matched: list[tuple[str, str]]) -> str:
        """Lines with glossary names are cached per spelling, so editing a name takes effect at once."""
        if not matched:
            return self.engine.name
        import hashlib

        marked = sorted((en, ar, en in self.female) for en, ar in matched)
        sig = hashlib.sha1(repr(marked).encode("utf-8")).hexdigest()[:10]
        return f"{self.engine.name}#n2-{sig}"

    def _translate_with_names(self, key: str, matched: list[tuple[str, str]]) -> str:
        modes = {en: self.names.mode(en, ar) for en, ar in matched}
        patterns = {en: pattern for en, _ar, pattern in self._patterns}
        free = [p for p in PROXIES if not _name_rx(p[0]).search(key)]
        free_f = [p for p in PROXIES_FEMALE if not _name_rx(p[0]).search(key)]
        swaps: list[tuple[str, str]] = []  # (stand-in Arabic, agreed Arabic)
        source = key
        for en, ar in matched:
            pool = free_f if en in self.female else free
            # A woman's name always goes through a stand-in: the engine then gets her verbs right.
            if (modes[en][0] == "proxy" or en in self.female) and pool:
                pattern = patterns.get(en) or name_pattern(en)
                if not pattern.search(source):
                    continue  # it sat inside a longer name that already has its stand-in
                proxy_en, proxy_ar = pool.pop(0)
                source = pattern.sub(proxy_en, source)
                swaps.append((proxy_ar, ar))
        raw = self.engine.translate(source, self.history[-4:])
        if swaps and all(proxy_ar in raw for proxy_ar, _ in swaps):
            for proxy_ar, ar in swaps:
                raw = raw.replace(proxy_ar, ar)
        elif swaps:
            raw = self.engine.translate(key, self.history[-4:])  # a stand-in got lost: plain translation
        for en, ar in matched:
            mode, variant = modes[en]
            if mode == "variant" and variant and ar not in raw:
                raw = raw.replace(variant, ar)
        return apply_glossary(raw, key, dict(matched))

    def translate(self, text: str) -> tuple[str, bool, float]:
        """Returns (arabic, cache_hit, milliseconds)."""
        t0 = time.perf_counter()
        key = normalize_english(text)
        fixed = self.cache.get_fix(self.profile, key)
        if fixed is not None:
            return fixed, True, (time.perf_counter() - t0) * 1000.0
        matched = self._matched(key)
        engine_key = self._engine_key(matched)
        hit = self.cache.get(self.profile, key, engine_key, self.style)
        if hit is not None:
            return hit, True, (time.perf_counter() - t0) * 1000.0
        raw = self._translate_with_names(key, matched) if matched else self.engine.translate(key, self.history[-4:])
        if "(" not in key:
            raw = raw.replace("(", "").replace(")", "")  # the engine brackets names on its own
        ar = normalize_arabic(raw)
        if not ar:
            raise TranslateError(f"empty translation for {key!r}")
        self.cache.put(self.profile, key, engine_key, self.style, ar)
        self.history.append((key, ar))
        del self.history[:-8]
        return ar, False, (time.perf_counter() - t0) * 1000.0

    def fix(self, english: str, arabic: str | None) -> None:
        """Remember the user's own wording for a line (None: forget it)."""
        ar = normalize_arabic(arabic or "")
        self.cache.put_fix(self.profile, normalize_english(english), ar or None)


def dump_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def list_profiles() -> list[dict]:
    """Every game profile: file name and display title."""
    import yaml

    out = []
    for path in sorted((paths.REPO / "profiles").glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            data = {}
        title = data.get("title") if isinstance(data, dict) else None
        out.append({"name": path.stem, "title": str(title or path.stem)})
    return out


def save_profile(name: str, data: dict) -> None:
    import yaml

    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,40}", name):
        raise TranslateError("profile names use small English letters, digits, - and _ only")
    path = paths.REPO / "profiles" / f"{name}.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
