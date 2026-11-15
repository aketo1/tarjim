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
        self.path = Path(path) if path else CACHE_FILE
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS tr (profile TEXT, en TEXT, engine TEXT, style TEXT, ar TEXT, ts REAL,"
            " PRIMARY KEY (profile, en, engine, style))"
        )
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
        parts = split_sentences(text)
        src = [["eng_Latn"] + self._sp.encode(p, out_type=str) + ["</s>"] for p in parts]
        res = self._tr.translate_batch(
            src, target_prefix=[["arb_Arab"]] * len(src), beam_size=2, max_decoding_length=128,
            repetition_penalty=1.1,
        )
        # hypotheses[0][0] is the language token
        return join_sentences(parts, [self._sp.decode(r.hypotheses[0][1:]) for r in res])


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
        parts = split_sentences(text)
        src = [[">>ara<<"] + self._src.encode(p, out_type=str) + ["</s>"] for p in parts]
        res = self._tr.translate_batch(src, beam_size=2, max_decoding_length=128, repetition_penalty=1.1)
        return join_sentences(parts, [self._tgt.decode(r.hypotheses[0]) for r in res])


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


class CachedTranslator:
    """Cache first, then the engine; always returns cleaned Arabic."""

    def __init__(self, engine: Translator, cache: Cache, profile: str = "default", style: str = "msa",
                 glossary: dict[str, str] | None = None) -> None:
        self.engine = engine
        self.cache = cache
        self.profile = profile
        self.style = style
        self.glossary = glossary or {}
        self.history: list[tuple[str, str]] = []

    def translate(self, text: str) -> tuple[str, bool, float]:
        """Returns (arabic, cache_hit, milliseconds)."""
        t0 = time.perf_counter()
        key = normalize_english(text)
        hit = self.cache.get(self.profile, key, self.engine.name, self.style)
        if hit is not None:
            return hit, True, (time.perf_counter() - t0) * 1000.0
        raw = self.engine.translate(key, self.history[-4:])
        ar = normalize_arabic(apply_glossary(raw, key, self.glossary))
        if not ar:
            raise TranslateError(f"empty translation for {key!r}")
        self.cache.put(self.profile, key, self.engine.name, self.style, ar)
        self.history.append((key, ar))
        del self.history[:-8]
        return ar, False, (time.perf_counter() - t0) * 1000.0


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
