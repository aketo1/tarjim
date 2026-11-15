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


GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_TIMEOUT_S = 1.2

# Kept short on purpose: it is sent with every line, so every word costs tokens.
SYSTEM_PROMPT = """Translate English video-game dialogue into {style} subtitles.
Natural and concise, same tone. Names in Arabic letters (use the glossary).
No diacritics. Output only the Arabic line."""

STYLES = {
    "msa": "simple Modern Standard Arabic",
    "gulf": "Gulf (Saudi) colloquial Arabic",
}


def load_env_key(name: str = "GEMINI_API_KEY") -> str | None:
    """Read a key from the environment or the repo's .env file (never logged)."""
    import os

    value = os.environ.get(name)
    if value:
        return value.strip()
    env = paths.REPO / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line.startswith(f"{name}=") and not line.startswith("#"):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                return value or None
    return None


class GeminiTranslator:
    """Gemini through the Google Gen AI SDK (Interactions API). Falls back to a
    local engine when the call fails or takes longer than the timeout.

    `store=False` matters: without it the service saves every interaction and
    each call took about 2.3 s here instead of about 0.9 s.
    """

    name = "gemini"
    CONTEXT_LINES = 2
    QUOTA_COOLDOWN_S = 60.0
    ERROR_COOLDOWN_S = 20.0

    def __init__(self, fallback: Translator | None = None, model: str | None = None, style: str = "msa",
                 glossary: dict[str, str] | None = None, timeout_s: float = GEMINI_TIMEOUT_S) -> None:
        key = load_env_key()
        if not key:
            raise TranslateError("no GEMINI_API_KEY in .env")
        from google import genai
        from google.genai import types

        # One attempt only: a retry would arrive long after the line left the screen.
        self._client = genai.Client(
            api_key=key, http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1))
        )
        self.model = model or paths.load_config().get("gemini_model", GEMINI_MODEL)
        self.fallback = fallback
        self.timeout_s = timeout_s
        self.glossary = glossary or {}
        self._system = SYSTEM_PROMPT.format(style=STYLES.get(style, style))
        self.calls = 0
        self.fallbacks = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.last_used = "gemini"
        self.last_error: str | None = None
        self._paused_until = 0.0
        self._failures = 0

    def warm_up(self) -> None:
        """Open the connection (the first call took about 3 s here) and load the fallback."""
        if self.fallback is not None:
            self.fallback.translate("Hello.")
        saved = self.timeout_s
        self.timeout_s = 8.0
        try:
            self.translate("Hello.")
        finally:
            self.timeout_s = saved
            self._failures = 0

    def _input(self, text: str, context: list[tuple[str, str]] | None) -> str:
        parts = []
        used = {en: ar for en, ar in self.glossary.items() if re.search(rf"\b{re.escape(en)}\b", text, re.IGNORECASE)}
        if used:
            parts.append("Glossary: " + "; ".join(f"{en}={ar}" for en, ar in used.items()))
        if context:
            parts.append("Before: " + " / ".join(en for en, _ in context[-self.CONTEXT_LINES :]))
        parts.append(f"Line: {text}")
        return "\n".join(parts)

    def _use_fallback(self, text: str, context, exc: Exception | None) -> str:
        if self.fallback is None:
            raise TranslateError(f"Gemini failed: {self.last_error}") from exc
        self.fallbacks += 1
        self.last_used = self.fallback.name
        return self.fallback.translate(text, context)

    def translate(self, text: str, context: list[tuple[str, str]] | None = None) -> str:
        if time.monotonic() < self._paused_until:
            return self._use_fallback(text, context, None)
        try:
            self.calls += 1
            interaction = self._client.interactions.create(
                model=self.model,
                system_instruction=self._system,
                input=self._input(text, context),
                generation_config={"thinking_level": "minimal", "max_output_tokens": 160, "temperature": 0.2},
                store=False,
                timeout=self.timeout_s,
            )
            out = (interaction.output_text or "").strip()
            if not out:
                raise TranslateError("empty answer")
            usage = getattr(interaction, "usage", None)
            self.tokens_in += int(getattr(usage, "total_input_tokens", 0) or 0)
            self.tokens_out += int(getattr(usage, "total_output_tokens", 0) or 0)
            self.last_used = "gemini"
            self._failures = 0
            return " ".join(line.strip() for line in out.splitlines() if line.strip())
        except Exception as exc:  # network, quota, timeout, bad key: all handled the same way
            self.last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
            quota = "429" in self.last_error or "RESOURCE_EXHAUSTED" in self.last_error
            self._failures += 1
            if quota:
                # Out of quota: asking again only wastes the timeout on every line.
                self._paused_until = time.monotonic() + self.QUOTA_COOLDOWN_S
            elif self._failures >= 3:
                self._paused_until = time.monotonic() + self.ERROR_COOLDOWN_S
            return self._use_fallback(text, context, exc)


ENGINES = {"nllb-600m": NllbTranslator, "opus-big": OpusTranslator}
LOCAL_DEFAULT = "opus-big"


def make_engine(name: str, glossary: dict[str, str] | None = None, style: str = "msa") -> Translator:
    if name == "gemini":
        return GeminiTranslator(fallback=ENGINES[LOCAL_DEFAULT](), glossary=glossary, style=style)
    if name not in ENGINES:
        raise TranslateError(f"unknown engine {name!r}; choose from gemini, {', '.join(ENGINES)}")
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
        # When Gemini fell back to the local engine, file the answer under the
        # engine that really produced it, so Gemini gets another try next time.
        produced_by = getattr(self.engine, "last_used", self.engine.name)
        self.cache.put(self.profile, key, produced_by, self.style, ar)
        self.history.append((key, ar))
        del self.history[:-8]
        return ar, False, (time.perf_counter() - t0) * 1000.0


def dump_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)
