"""Short Arabic console messages. Forces UTF-8 so Windows consoles print them."""

from __future__ import annotations

import sys


def setup_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


_hook = None


def set_hook(fn) -> None:
    """fn(kind, message) is called for every message; kind is step/ok/info/warn/fail."""
    global _hook
    _hook = fn


def _emit(kind: str, msg: str) -> None:
    if _hook is not None:
        try:
            _hook(kind, msg)
        except Exception:  # a broken listener must never break the work itself
            pass


def step(msg: str) -> None:
    _emit("step", msg)
    print(f"… {msg}", flush=True)


def ok(msg: str) -> None:
    _emit("ok", msg)
    print(f"✔ {msg}", flush=True)


def info(msg: str) -> None:
    _emit("info", msg)
    print(f"  {msg}", flush=True)


def warn(msg: str) -> None:
    _emit("warn", msg)
    print(f"⚠ {msg}", flush=True)


def fail(msg: str) -> None:
    _emit("fail", msg)
    print(f"✖ {msg}", file=sys.stderr, flush=True)
