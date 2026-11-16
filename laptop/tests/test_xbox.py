"""Xbox source: the parts that can be checked without a console or a Microsoft account."""

import cv2
import numpy as np
import pytest

from tarjim.app.session import friendly_error
from tarjim.sources import xbox


def test_frames_from_the_window_reach_the_pipeline_at_1080p():
    source = xbox.XboxSource()
    picture = np.full((720, 1280, 3), (10, 120, 240), np.uint8)
    ok, jpeg = cv2.imencode(".jpg", picture)
    assert ok and source.push_jpeg(jpeg.tobytes())
    assert not source.push_jpeg(b"not a picture")
    frames = source.frames()
    frame, t_capture, seq = next(frames)
    assert frame.shape == (1080, 1920, 3) and seq == 1 and t_capture > 0
    assert abs(int(frame[500, 900, 2]) - 240) < 6  # still the same colour (BGR)
    info = source.info()
    assert (info.width, info.height, info.backend) == (1920, 1080, "xbox-webrtc")
    source.close()
    assert list(frames) == []


def test_a_failed_stream_ends_the_session_instead_of_hanging():
    source = xbox.XboxSource()
    source.state = "failed"
    source.last_error = "boom"
    assert list(source.frames()) == []


def test_unlinked_account_is_reported_in_plain_arabic(tmp_path, monkeypatch):
    monkeypatch.setattr(xbox, "TOKEN_FILE", tmp_path / "xbox-tokens.json")
    auth = xbox.XboxAuth()
    assert auth.linked is False
    with pytest.raises(xbox.XboxError) as err:
        auth.streaming()
    message = friendly_error(err.value)
    assert "الإكس بوكس" in message and "PS5" not in message


def test_region_host_comes_from_the_default_region(tmp_path, monkeypatch):
    monkeypatch.setattr(xbox, "TOKEN_FILE", tmp_path / "xbox-tokens.json")
    (tmp_path / "xbox-tokens.json").write_text('{"refresh_token": "r1"}', encoding="utf-8")
    calls = []

    def fake_post(host, path, body, headers, timeout=15.0):
        calls.append((host, path))
        if host == "login.microsoftonline.com":
            return {"access_token": "a1", "refresh_token": "r2"}
        if host in ("user.auth.xboxlive.com", "xsts.auth.xboxlive.com"):
            return {"Token": "t-" + host.split(".")[0]}
        return {"gsToken": "gs", "durationInSeconds": 3600, "offeringSettings": {"regions": [
            {"name": "A", "baseUri": "https://a.example.test", "isDefault": False},
            {"name": "B", "baseUri": "https://b.example.test", "isDefault": True}]}}

    monkeypatch.setattr(xbox, "_post", fake_post)
    auth = xbox.XboxAuth()
    gs = auth.streaming()
    assert (gs["token"], gs["host"]) == ("gs", "b.example.test")
    assert [c[0] for c in calls] == ["login.microsoftonline.com", "user.auth.xboxlive.com", "xsts.auth.xboxlive.com",
                                     "xhome.gssv-play-prod.xboxlive.com"]
    assert "r2" in (tmp_path / "xbox-tokens.json").read_text(encoding="utf-8")  # the rotated refresh token is kept
    auth.streaming()
    assert len(calls) == 4  # cached: no second round of sign-in calls
