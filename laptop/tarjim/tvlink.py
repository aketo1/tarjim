"""Laptop side of the TV protocol: connect, ping, show/keep/clear, collect acks."""

from __future__ import annotations

import socket
import threading
import time
from collections import OrderedDict

from . import protocol as P


def now_ms() -> float:
    return time.monotonic() * 1000.0


class TvLinkError(Exception):
    pass


class TvLink:
    """One TCP connection to the TV overlay app.

    A background thread reads replies; another pings every 300 ms and
    reconnects after a drop. All public methods are thread-safe.
    """

    def __init__(self, host: str, port: int = P.DEFAULT_PORT, *, auto_reconnect: bool = True) -> None:
        self.host = host
        self.port = port
        self.auto_reconnect = auto_reconnect
        self.caps: dict = {}
        self.clock_offset_ms: float | None = None  # tv_clock - laptop_clock
        self.rtt_ms: float | None = None
        self.reconnects = 0
        self._sock: socket.socket | None = None
        self._send_lock = threading.Lock()
        self._state = threading.Condition()
        self._acks: OrderedDict[int, dict] = OrderedDict()
        self._seq = 0
        self._closing = False
        self._threads: list[threading.Thread] = []
        self._best_rtt = float("inf")

    # -- connection -------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def connect(self, timeout: float = 3.0) -> dict:
        self._open(timeout)
        if not self._threads:
            t = threading.Thread(target=self._ping_loop, name="tvlink-ping", daemon=True)
            t.start()
            self._threads.append(t)
        return self.caps

    def _open(self, timeout: float, reconnect: bool = False) -> None:
        try:
            sock = socket.create_connection((self.host, self.port), timeout=timeout)
        except OSError as exc:
            raise TvLinkError(f"cannot connect to {self.host}:{self.port}: {exc}") from exc
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(timeout)
        decoder = P.FrameDecoder()
        try:
            sock.sendall(P.msg_hello())
            ack = None
            while ack is None:
                data = sock.recv(65536)
                if not data:
                    raise TvLinkError("TV closed the connection during the handshake")
                for header, _ in decoder.feed(data):
                    if header["type"] == "hello_ack":
                        ack = header
        except (OSError, P.ProtocolError) as exc:
            sock.close()
            raise TvLinkError(f"handshake failed: {exc}") from exc
        if ack.get("v") != P.PROTOCOL_VERSION:
            sock.close()
            raise TvLinkError(f"TV speaks protocol v{ack.get('v')}, laptop v{P.PROTOCOL_VERSION}")
        sock.settimeout(None)
        self.caps = ack
        self._best_rtt = float("inf")
        with self._state:
            if reconnect:
                self.reconnects += 1
            self._sock = sock
            self._state.notify_all()
        reader = threading.Thread(target=self._read_loop, args=(sock, decoder), name="tvlink-read", daemon=True)
        reader.start()

    def close(self) -> None:
        self._closing = True
        sock = self._sock
        if sock is not None:
            try:
                self._send(P.msg_clear(None))
            except TvLinkError:
                pass
        self._drop(sock)

    def _drop(self, sock: socket.socket | None) -> None:
        if sock is None:
            return
        with self._state:
            if self._sock is sock:
                self._sock = None
            self._state.notify_all()
        try:
            sock.close()
        except OSError:
            pass

    # -- background threads -----------------------------------------------

    def _read_loop(self, sock: socket.socket, decoder: P.FrameDecoder) -> None:
        try:
            while True:
                data = sock.recv(65536)
                if not data:
                    break
                for header, _ in decoder.feed(data):
                    self._on_message(header)
        except (OSError, P.ProtocolError):
            pass
        self._drop(sock)

    def _on_message(self, header: dict) -> None:
        kind = header["type"]
        if kind == "pong":
            t1 = now_ms()
            rtt = t1 - float(header["ts"])
            # The sample with the smallest round trip gives the best offset.
            if rtt <= self._best_rtt:
                self._best_rtt = rtt
                self.clock_offset_ms = float(header["tv_ts"]) - (float(header["ts"]) + rtt / 2.0)
            self.rtt_ms = rtt
        elif kind == "ack":
            header["t_ack_recv"] = now_ms()
            with self._state:
                self._acks[int(header["seq"])] = header
                while len(self._acks) > 256:
                    self._acks.popitem(last=False)
                self._state.notify_all()

    def _ping_loop(self) -> None:
        while not self._closing:
            if self._sock is None:
                if self.auto_reconnect:
                    try:
                        self._open(timeout=1.0, reconnect=True)
                    except TvLinkError:
                        time.sleep(0.5)
                        continue
                else:
                    return
            try:
                self._send(P.msg_ping(now_ms()))
            except TvLinkError:
                pass
            time.sleep(P.PING_INTERVAL_MS / 1000.0)

    # -- sending ----------------------------------------------------------

    def _send(self, frame: bytes) -> None:
        sock = self._sock
        if sock is None:
            raise TvLinkError("not connected")
        try:
            with self._send_lock:
                sock.sendall(frame)
        except OSError as exc:
            self._drop(sock)
            raise TvLinkError(f"send failed: {exc}") from exc

    def show(self, win: str, layers: list[P.Layer]) -> int:
        with self._state:
            self._seq += 1
            seq = self._seq
        self._send(P.msg_show(seq, win, layers))
        return seq

    def keep(self, ids: list[str]) -> None:
        self._send(P.msg_keep(ids))

    def clear(self, ids: list[str] | None = None, fade_ms: int = 0) -> None:
        self._send(P.msg_clear(ids, fade_ms))

    def wait_ack(self, seq: int, timeout: float = 2.0) -> dict | None:
        deadline = time.monotonic() + timeout
        with self._state:
            while seq not in self._acks:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._state.wait(remaining)
            return self._acks[seq]

    def wait_connected(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        with self._state:
            while self._sock is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._state.wait(remaining)
            return True

    def tv_time_to_laptop(self, tv_ms: float) -> float | None:
        if self.clock_offset_ms is None:
            return None
        return tv_ms - self.clock_offset_ms

    def __enter__(self) -> "TvLink":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
