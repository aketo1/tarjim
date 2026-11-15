"""FakeTv: a Python implementation of the TV side of protocol v1.

It keeps the same layer rules as the Android app (TTL, 1000 ms watchdog,
4 layers per window, one client at a time) and can composite its layers onto
a frame, so the whole pipeline is testable without the TV.

Difference from the real app: fades are applied instantly.
"""

from __future__ import annotations

import io
import socket
import threading
import time
from dataclasses import dataclass

from PIL import Image

from . import protocol as P


def _now_ms() -> float:
    return time.monotonic() * 1000.0


@dataclass
class FakeLayer:
    id: str
    win: str
    z: int
    x: int
    y: int
    w: int
    h: int
    ttl_ms: int
    expires_at: float
    image: Image.Image
    seq: int


class FakeTv:
    def __init__(self, width: int = 1920, height: int = 1080, port: int = 0, host: str = "127.0.0.1") -> None:
        self.width = width
        self.height = height
        self._lock = threading.Lock()
        self._layers: dict[str, FakeLayer] = {}
        self._last_msg = _now_ms()
        self._client: socket.socket | None = None
        self._stop = threading.Event()
        self.shows = 0
        self.draw_log: list[tuple[float, int, list[str]]] = []  # (t_ms, seq, layer ids drawn together)
        self.closed_for_error = 0
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((host, port))
        self._server.listen(2)
        self.port = self._server.getsockname()[1]
        self.host = host
        threading.Thread(target=self._accept_loop, name="faketv-accept", daemon=True).start()
        threading.Thread(target=self._watchdog_loop, name="faketv-watchdog", daemon=True).start()

    # -- public -----------------------------------------------------------

    def layers(self) -> dict[str, FakeLayer]:
        with self._lock:
            return dict(self._layers)

    def layer_ids(self) -> list[str]:
        return sorted(self.layers())

    def composite(self, base: Image.Image | None = None, win: str | None = None) -> Image.Image:
        """Draw the current layers over `base` (resized to the overlay plane)."""
        if base is None:
            canvas = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 255))
        else:
            canvas = base.convert("RGBA")
            if canvas.size != (self.width, self.height):
                canvas = canvas.resize((self.width, self.height), Image.BILINEAR)
        with self._lock:
            ordered = sorted(self._layers.values(), key=lambda l: (l.z, l.id))
            for layer in ordered:
                if win is not None and layer.win != win:
                    continue
                if _inside(layer, self.width, self.height):
                    canvas.alpha_composite(layer.image, (layer.x, layer.y))
                else:
                    _paste_clipped(canvas, layer)
        return canvas

    def close(self) -> None:
        self._stop.set()
        try:
            self._server.close()
        except OSError:
            pass
        client = self._client
        if client is not None:
            try:
                client.close()
            except OSError:
                pass

    def __enter__(self) -> "FakeTv":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- server -----------------------------------------------------------

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            old = self._client
            self._client = conn
            if old is not None:  # a new connection replaces the old one
                try:
                    old.close()
                except OSError:
                    pass
            self._clear_all()
            threading.Thread(target=self._client_loop, args=(conn,), name="faketv-client", daemon=True).start()

    def _client_loop(self, conn: socket.socket) -> None:
        decoder = P.FrameDecoder()
        send_lock = threading.Lock()

        def send(header: dict) -> None:
            with send_lock:
                conn.sendall(P.encode_frame(header))

        try:
            while True:
                data = conn.recv(65536)
                if not data:
                    break
                for header, payload in decoder.feed(data):
                    self._handle(header, payload, send)
        except P.ProtocolError:
            self.closed_for_error += 1
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass
            if self._client is conn:
                self._client = None
                self._clear_all()  # disconnect clears everything

    def _handle(self, header: dict, payload: bytes, send) -> None:
        with self._lock:
            self._last_msg = _now_ms()
        kind = header["type"]
        if kind == "hello":
            if header.get("v") != P.PROTOCOL_VERSION:
                raise P.ProtocolError("unsupported protocol version")
            send(
                {
                    "type": "hello_ack",
                    "v": P.PROTOCOL_VERSION,
                    "w": self.width,
                    "h": self.height,
                    "density": 320,
                    "sdk": 0,
                    "model": "FakeTv",
                    "windows": ["A", "B"],
                }
            )
        elif kind == "ping":
            send({"type": "pong", "ts": header.get("ts"), "tv_ts": _now_ms()})
        elif kind == "show":
            self._handle_show(header, payload, send)
        elif kind == "keep":
            now = _now_ms()
            with self._lock:
                for layer_id in _str_list(header.get("ids")):
                    layer = self._layers.get(layer_id)
                    if layer is not None:
                        layer.expires_at = now + layer.ttl_ms
        elif kind == "clear":
            if header.get("all") is True:
                self._clear_all()
            else:
                with self._lock:
                    for layer_id in _str_list(header.get("ids")):
                        self._layers.pop(layer_id, None)
        else:
            raise P.ProtocolError(f"unknown message type {kind!r}")

    def _handle_show(self, header: dict, payload: bytes, send) -> None:
        t_recv = _now_ms()
        seq = header.get("seq")
        win = header.get("win")
        entries = header.get("layers")
        if not isinstance(seq, int) or win not in ("A", "B") or not isinstance(entries, list) or not entries:
            raise P.ProtocolError("bad show header")
        decoded: list[FakeLayer] = []
        for e in entries:
            try:
                layer_id = e["id"]
                x, y, w, h, z = int(e["x"]), int(e["y"]), int(e["w"]), int(e["h"]), int(e["z"])
                ttl, off, length = int(e["ttl_ms"]), int(e["offset"]), int(e["len"])
            except (KeyError, TypeError, ValueError) as exc:
                raise P.ProtocolError(f"bad layer entry: {exc}") from exc
            if not isinstance(layer_id, str) or not layer_id:
                raise P.ProtocolError("layer id must be a non-empty string")
            P.validate_layer_geometry(w, h)
            if off < 0 or length <= 0 or off + length > len(payload) or ttl <= 0:
                raise P.ProtocolError("layer bytes outside the payload")
            try:
                img = Image.open(io.BytesIO(payload[off : off + length]))
                img.load()
            except Exception as exc:  # Pillow raises several types for bad data
                raise P.ProtocolError(f"layer {layer_id}: not a decodable image: {exc}") from exc
            if img.size != (w, h):
                raise P.ProtocolError(f"layer {layer_id}: image is {img.size}, header says {w}x{h}")
            decoded.append(FakeLayer(layer_id, win, z, x, y, w, h, ttl, 0.0, img.convert("RGBA"), seq))
        t_decoded = _now_ms()
        with self._lock:  # atomic: all layers of one show appear together
            now = _now_ms()
            merged = dict(self._layers)
            for layer in decoded:
                current = merged.get(layer.id)
                if current is not None and current.seq > layer.seq:
                    continue  # an older seq never replaces a newer one
                layer.expires_at = now + layer.ttl_ms
                merged[layer.id] = layer
            for w_name in ("A", "B"):
                if sum(1 for l in merged.values() if l.win == w_name) > P.MAX_LAYERS:
                    raise P.ProtocolError(f"more than {P.MAX_LAYERS} layers in window {w_name}")
            self._layers = merged
            self.shows += 1
            t_drawn = _now_ms()
            self.draw_log.append((t_drawn, seq, [l.id for l in decoded]))
        send({"type": "ack", "seq": seq, "t_recv": t_recv, "t_decoded": t_decoded, "t_drawn": t_drawn})

    # -- fail-safe --------------------------------------------------------

    def _clear_all(self) -> None:
        with self._lock:
            self._layers = {}

    def _watchdog_loop(self) -> None:
        while not self._stop.wait(0.05):
            now = _now_ms()
            with self._lock:
                if self._layers and now - self._last_msg > P.WATCHDOG_MS:
                    self._layers = {}
                    continue
                expired = [k for k, l in self._layers.items() if l.expires_at <= now]
                for k in expired:
                    del self._layers[k]


def _str_list(value) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise P.ProtocolError("ids must be a list of strings")
    return value


def _inside(layer: FakeLayer, width: int, height: int) -> bool:
    return layer.x >= 0 and layer.y >= 0 and layer.x + layer.w <= width and layer.y + layer.h <= height


def _paste_clipped(canvas: Image.Image, layer: FakeLayer) -> None:
    tmp = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    tmp.paste(layer.image, (layer.x, layer.y))
    canvas.alpha_composite(tmp)
