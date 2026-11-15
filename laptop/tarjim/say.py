"""Short Arabic console messages. Forces UTF-8 so Windows consoles print them."""

from __future__ import annotations

import sys


def setup_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def step(msg: str) -> None:
    print(f"… {msg}", flush=True)


def ok(msg: str) -> None:
    print(f"✔ {msg}", flush=True)


def info(msg: str) -> None:
    print(f"  {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"⚠ {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"✖ {msg}", file=sys.stderr, flush=True)
