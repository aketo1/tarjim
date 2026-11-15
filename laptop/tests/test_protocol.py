import io
import socket
import struct
import time

import pytest
from PIL import Image

from tarjim import protocol as P
from tarjim.faketv import FakeTv
from tarjim.tvlink import TvLink


def png(w, h, color=(255, 0, 0, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), color).save(buf, format="PNG", compress_level=1)
    return buf.getvalue()


def layer(layer_id, x=0, y=0, w=8, h=8, color=(255, 0, 0, 255), ttl_ms=1000, z=0) -> P.Layer:
    return P.Layer(id=layer_id, png=png(w, h, color), x=x, y=y, w=w, h=h, z=z, ttl_ms=ttl_ms)


def wait_until(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def raw_client(tv: FakeTv) -> socket.socket:
    s = socket.create_connection((tv.host, tv.port), timeout=2)
    s.sendall(P.msg_hello())
    dec = P.FrameDecoder()
    while not dec.feed(s.recv(65536)):
        pass
    return s


def is_closed(s: socket.socket) -> bool:
    s.settimeout(2)
    try:
        while True:
            if s.recv(65536) == b"":
                return True
    except (ConnectionError, OSError):
        return True


# -- framing ---------------------------------------------------------------


def test_frame_roundtrip_with_arabic_and_payload():
    frame = P.encode_frame({"type": "x", "text": "مرحبا"}, b"\x00\x01\x02")
    assert P.FrameDecoder().feed(frame) == [({"type": "x", "text": "مرحبا"}, b"\x00\x01\x02")]


def test_fragmented_frames_byte_by_byte():
    stream = P.encode_frame({"type": "a"}, b"12345") + P.encode_frame({"type": "b"}) + P.msg_keep(["k"])
    dec = P.FrameDecoder()
    got = []
    for i in range(len(stream)):
        got += dec.feed(stream[i : i + 1])
    assert [h["type"] for h, _ in got] == ["a", "b", "keep"]
    assert got[0][1] == b"12345"


@pytest.mark.parametrize(
    "raw",
    [
        struct.pack(">II", 0, 0),
        struct.pack(">II", P.MAX_JSON_LEN + 1, 0),
        struct.pack(">II", 2, P.MAX_BIN_LEN + 1),
        struct.pack(">II", 5, 0) + b"{nope",
        struct.pack(">II", 2, 0) + b"[]",
        struct.pack(">II", 9, 0) + b'{"type":1',
        struct.pack(">II", 2, 0) + b"\xff\xfe",
    ],
)
def test_malformed_frames_raise(raw):
    with pytest.raises(P.ProtocolError):
        P.FrameDecoder().feed(raw)


def test_show_rejects_bad_layers():
    with pytest.raises(P.ProtocolError):
        P.msg_show(1, "C", [layer("a")])
    with pytest.raises(P.ProtocolError):
        P.msg_show(1, "A", [])
    with pytest.raises(P.ProtocolError):
        P.msg_show(1, "A", [layer(str(i)) for i in range(5)])
    with pytest.raises(P.ProtocolError):
        P.msg_show(1, "A", [P.Layer("big", b"x", 0, 0, 1921, 10)])
    with pytest.raises(P.ProtocolError):
        P.msg_show(1, "A", [P.Layer("float", b"x", 0.5, 0, 10, 10)])


# -- FakeTv + TvLink -------------------------------------------------------


def test_handshake_ping_and_clock_offset():
    with FakeTv() as tv, TvLink(tv.host, tv.port) as link:
        caps = link.connect()
        assert (caps["w"], caps["h"], caps["windows"]) == (1920, 1080, ["A", "B"])
        assert wait_until(lambda: link.clock_offset_ms is not None)
        assert abs(link.clock_offset_ms) < 50  # same machine, same clock
        assert link.rtt_ms < 200


def test_atomic_multi_layer_show_and_ack():
    with FakeTv() as tv, TvLink(tv.host, tv.port) as link:
        link.connect()
        seq = link.show("A", [layer("fill", 10, 20, color=(0, 255, 0, 255)), layer("text", 30, 20, z=1)])
        ack = link.wait_ack(seq)
        assert ack is not None and ack["t_recv"] <= ack["t_decoded"] <= ack["t_drawn"]
        assert tv.layer_ids() == ["fill", "text"]
        assert tv.draw_log[-1][2] == ["fill", "text"]  # both arrived in one draw
        img = tv.composite()
        assert img.getpixel((12, 22)) == (0, 255, 0, 255)
        assert img.getpixel((32, 22)) == (255, 0, 0, 255)
        assert img.getpixel((100, 100)) == (0, 0, 0, 255)


def test_ttl_expiry_and_keep():
    with FakeTv() as tv, TvLink(tv.host, tv.port) as link:
        link.connect()
        link.wait_ack(link.show("A", [layer("short", ttl_ms=200), layer("kept", ttl_ms=200)]))
        for _ in range(8):  # 0.6 s of keeps for one layer only
            link.keep(["kept"])
            time.sleep(0.075)
        assert tv.layer_ids() == ["kept"]
        assert wait_until(lambda: tv.layer_ids() == [], timeout=1.0)


def test_clear_ids_and_all():
    with FakeTv() as tv, TvLink(tv.host, tv.port) as link:
        link.connect()
        link.wait_ack(link.show("B", [layer("a", ttl_ms=5000), layer("b", ttl_ms=5000), layer("c", ttl_ms=5000)]))
        link.clear(["a"])
        assert wait_until(lambda: tv.layer_ids() == ["b", "c"])
        link.clear(None)
        assert wait_until(lambda: tv.layer_ids() == [])


def test_watchdog_clears_when_laptop_goes_silent():
    with FakeTv() as tv:
        s = raw_client(tv)  # raw socket: no pings after the show
        s.sendall(P.msg_show(1, "A", [layer("stale", ttl_ms=60000)]))
        assert wait_until(lambda: tv.layer_ids() == ["stale"])
        t0 = time.monotonic()
        assert wait_until(lambda: tv.layer_ids() == [], timeout=2.0)
        assert 0.8 <= time.monotonic() - t0 <= 1.3
        s.close()


def test_disconnect_clears_everything():
    with FakeTv() as tv:
        s = raw_client(tv)
        s.sendall(P.msg_show(1, "A", [layer("x", ttl_ms=60000)]))
        assert wait_until(lambda: tv.layer_ids() == ["x"])
        s.close()
        assert wait_until(lambda: tv.layer_ids() == [], timeout=0.5)


@pytest.mark.parametrize(
    "frame",
    [
        struct.pack(">II", 4, 0) + b"oops",
        P.encode_frame({"type": "launch_missiles"}),
        P.encode_frame({"type": "show", "seq": 1, "win": "A", "layers": []}),
        P.encode_frame(
            {
                "type": "show",
                "seq": 1,
                "win": "A",
                "layers": [{"id": "a", "z": 0, "x": 0, "y": 0, "w": 8, "h": 8, "ttl_ms": 500, "fade_ms": 0, "offset": 0, "len": 999}],
            },
            b"short",
        ),
        P.encode_frame(
            {
                "type": "show",
                "seq": 1,
                "win": "A",
                "layers": [{"id": "a", "z": 0, "x": 0, "y": 0, "w": 8, "h": 8, "ttl_ms": 500, "fade_ms": 0, "offset": 0, "len": 7}],
            },
            b"notapng",
        ),
    ],
)
def test_malformed_input_closes_connection_but_server_survives(frame):
    with FakeTv() as tv:
        s = raw_client(tv)
        s.sendall(frame)
        assert is_closed(s)
        assert tv.closed_for_error == 1
        with TvLink(tv.host, tv.port) as link:  # the server still accepts clients
            link.connect()
            assert link.wait_ack(link.show("A", [layer("ok")])) is not None


def test_fifth_layer_in_one_window_is_rejected():
    with FakeTv() as tv:
        s = raw_client(tv)
        s.sendall(P.msg_show(1, "A", [layer(str(i), ttl_ms=5000) for i in range(4)]))
        assert wait_until(lambda: len(tv.layer_ids()) == 4)
        s.sendall(P.msg_show(2, "A", [layer("five", ttl_ms=5000)]))
        assert is_closed(s)


def test_older_seq_never_replaces_newer():
    with FakeTv() as tv:
        s = raw_client(tv)
        s.sendall(P.msg_show(5, "A", [layer("a", color=(0, 0, 255, 255), ttl_ms=5000)]))
        s.sendall(P.msg_show(3, "A", [layer("a", color=(255, 0, 0, 255), ttl_ms=5000)]))
        assert wait_until(lambda: tv.shows == 2)
        assert tv.composite().getpixel((2, 2)) == (0, 0, 255, 255)
        s.close()


def test_new_connection_replaces_old():
    with FakeTv() as tv:
        first = raw_client(tv)
        first.sendall(P.msg_show(1, "A", [layer("old", ttl_ms=60000)]))
        assert wait_until(lambda: tv.layer_ids() == ["old"])
        second = raw_client(tv)
        assert is_closed(first)
        assert tv.layer_ids() == []
        second.close()


def test_reconnect_after_tv_restart():
    tv = FakeTv()
    port = tv.port
    link = TvLink(tv.host, port)
    link.connect()
    tv.close()
    assert wait_until(lambda: not link.connected, timeout=3.0)
    tv2 = FakeTv(port=port)
    try:
        assert link.wait_connected(timeout=5.0)
        assert link.reconnects >= 1
        assert link.wait_ack(link.show("A", [layer("again")])) is not None
    finally:
        link.close()
        tv2.close()
