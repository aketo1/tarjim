"""Tarjim wire protocol v1 (see docs/PROTOCOL.md).

Frame layout: uint32 BE json_len, uint32 BE bin_len, JSON header (UTF-8),
binary payload. The same rules are implemented in Kotlin on the TV.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass

PROTOCOL_VERSION = 1
DEFAULT_PORT = 47800

MAX_JSON_LEN = 64 * 1024
MAX_BIN_LEN = 8 * 1024 * 1024
MAX_LAYERS = 4
MAX_LAYER_W = 1920
MAX_LAYER_H = 480

PING_INTERVAL_MS = 300
WATCHDOG_MS = 1000

_PREFIX = struct.Struct(">II")


class ProtocolError(Exception):
    """A frame or message broke the protocol; the connection must be closed."""


@dataclass(frozen=True)
class Layer:
    """One overlay layer: a PNG drawn 1:1 at (x, y) in overlay pixels."""

    id: str
    png: bytes
    x: int
    y: int
    w: int
    h: int
    z: int = 0
    ttl_ms: int = 1000
    fade_ms: int = 0


def encode_frame(header: dict, payload: bytes = b"") -> bytes:
    body = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_JSON_LEN:
        raise ProtocolError(f"json header too large: {len(body)}")
    if len(payload) > MAX_BIN_LEN:
        raise ProtocolError(f"binary payload too large: {len(payload)}")
    return _PREFIX.pack(len(body), len(payload)) + body + payload


class FrameDecoder:
    """Incremental decoder; feed it whatever the socket returns."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[tuple[dict, bytes]]:
        self._buf += data
        out: list[tuple[dict, bytes]] = []
        while True:
            if len(self._buf) < _PREFIX.size:
                return out
            json_len, bin_len = _PREFIX.unpack_from(self._buf, 0)
            if json_len == 0 or json_len > MAX_JSON_LEN:
                raise ProtocolError(f"bad json_len {json_len}")
            if bin_len > MAX_BIN_LEN:
                raise ProtocolError(f"bad bin_len {bin_len}")
            total = _PREFIX.size + json_len + bin_len
            if len(self._buf) < total:
                return out
            body = bytes(self._buf[_PREFIX.size : _PREFIX.size + json_len])
            payload = bytes(self._buf[_PREFIX.size + json_len : total])
            del self._buf[:total]
            try:
                header = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProtocolError(f"bad json header: {exc}") from exc
            if not isinstance(header, dict) or not isinstance(header.get("type"), str):
                raise ProtocolError("header must be an object with a string 'type'")
            out.append((header, payload))


def msg_hello() -> bytes:
    return encode_frame({"type": "hello", "v": PROTOCOL_VERSION})


def msg_ping(ts_ms: float) -> bytes:
    return encode_frame({"type": "ping", "ts": ts_ms})


def msg_show(seq: int, win: str, layers: list[Layer]) -> bytes:
    if win not in ("A", "B"):
        raise ProtocolError(f"bad window {win!r}")
    if not 1 <= len(layers) <= MAX_LAYERS:
        raise ProtocolError(f"a show carries 1..{MAX_LAYERS} layers, got {len(layers)}")
    entries = []
    blobs = []
    offset = 0
    for layer in layers:
        validate_layer_geometry(layer.w, layer.h)
        for name in ("x", "y", "w", "h", "z", "ttl_ms", "fade_ms"):
            if not isinstance(getattr(layer, name), int):
                raise ProtocolError(f"layer {layer.id}: {name} must be an integer")
        entries.append(
            {
                "id": layer.id,
                "z": layer.z,
                "x": layer.x,
                "y": layer.y,
                "w": layer.w,
                "h": layer.h,
                "ttl_ms": layer.ttl_ms,
                "fade_ms": layer.fade_ms,
                "offset": offset,
                "len": len(layer.png),
            }
        )
        blobs.append(layer.png)
        offset += len(layer.png)
    return encode_frame({"type": "show", "seq": seq, "win": win, "layers": entries}, b"".join(blobs))


def msg_keep(ids: list[str]) -> bytes:
    return encode_frame({"type": "keep", "ids": list(ids)})


def msg_clear(ids: list[str] | None = None, fade_ms: int = 0) -> bytes:
    header: dict = {"type": "clear", "fade_ms": int(fade_ms)}
    if ids is None:
        header["all"] = True
    else:
        header["ids"] = list(ids)
    return encode_frame(header)


def validate_layer_geometry(w: int, h: int) -> None:
    if not (1 <= w <= MAX_LAYER_W and 1 <= h <= MAX_LAYER_H):
        raise ProtocolError(f"layer size {w}x{h} outside 1..{MAX_LAYER_W} x 1..{MAX_LAYER_H}")
