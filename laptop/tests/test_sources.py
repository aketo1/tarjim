import threading
import time

import numpy as np
import pytest
from PIL import Image

from tarjim.sources import FrameBox, SourceError, open_source
from tarjim.sources.file import FileSource


def test_framebox_returns_newest_and_counts_drops():
    box = FrameBox()
    for i in range(5):
        box.put(f"f{i}")
    frame, _t, seq = box.get(timeout=0.1)
    assert (frame, seq) == ("f4", 5)
    assert box.dropped == 4
    assert box.get(timeout=0.05) is None  # nothing new
    box.put("f5")
    assert box.get(timeout=0.1)[0] == "f5"
    assert box.dropped == 4


def test_framebox_wakes_waiting_consumer_and_closes():
    box = FrameBox()
    got = []
    t = threading.Thread(target=lambda: got.append(box.get(timeout=2)))
    t.start()
    time.sleep(0.05)
    box.put("x")
    t.join(1)
    assert got[0][0] == "x"
    t = threading.Thread(target=lambda: got.append(box.get(timeout=2)))
    t.start()
    time.sleep(0.05)
    box.close()
    t.join(1)
    assert got[1] is None and not t.is_alive()


def test_framebox_fps():
    box = FrameBox()
    now = time.monotonic()
    for i in range(60):
        box.put(i, t_capture=now - 1.99 + i / 30)
    assert 28 <= box.fps() <= 31


def test_file_source_folder_order_bgr_and_timing(tmp_path):
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
    for i, c in enumerate(colors):
        Image.new("RGB", (64, 36), c).save(tmp_path / f"{i:02d}.png")
    (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")
    src = FileSource(tmp_path, fps=50)
    t0 = time.monotonic()
    out = list(src.frames())
    assert [seq for _, _, seq in out] == [1, 2, 3]
    assert 0.03 <= time.monotonic() - t0 < 0.5  # paced at 50 fps
    for (frame, _, _), (r, g, b) in zip(out, colors):
        assert frame.shape == (36, 64, 3) and frame.dtype == np.uint8
        assert tuple(int(v) for v in frame[0, 0]) == (b, g, r)  # BGR
    info = src.info()
    assert (info.width, info.height, info.backend) == (64, 36, "file")


def test_file_source_video_roundtrip(tmp_path):
    import av

    path = tmp_path / "clip.mp4"
    with av.open(str(path), "w") as container:
        stream = container.add_stream("mpeg4", rate=10)
        stream.width, stream.height, stream.pix_fmt = 64, 48, "yuv420p"
        for i in range(6):
            img = np.full((48, 64, 3), 40 * i, dtype=np.uint8)
            for packet in stream.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    frames = list(open_source("file", path=path, fps=0).frames())
    assert len(frames) == 6
    assert frames[0][0].shape == (48, 64, 3)
    assert frames[5][0].mean() > frames[0][0].mean() + 100


def test_file_source_loop_and_close(tmp_path):
    Image.new("RGB", (8, 8)).save(tmp_path / "a.png")
    src = FileSource(tmp_path, fps=0, loop=True)
    seen = 0
    for _ in src.frames():
        seen += 1
        if seen == 10:
            src.close()
    assert seen == 10


def test_bad_sources(tmp_path):
    with pytest.raises(SourceError):
        FileSource(tmp_path)  # empty folder
    with pytest.raises(SourceError):
        FileSource(tmp_path / "missing.mp4")
    with pytest.raises(SourceError):
        open_source("nope")
