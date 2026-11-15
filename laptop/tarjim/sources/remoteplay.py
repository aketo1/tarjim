"""`rp-pyremoteplay` backend: a receive-only Remote Play session.

Video only. This module never starts the library's controller worker and
never calls a controller method, so no button, stick or trigger state is ever
sent; the session is kept alive by the protocol's own heartbeats.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Iterator

import numpy as np

from .. import paths
from . import ps5
from .base import FrameBox, SourceError, SourceInfo

BACKEND = "rp-pyremoteplay"
RECONNECT_PAUSE_S = 1.0
STALL_S = 3.0  # no frame for this long while "connected" counts as a drop


def _stream_open(session) -> bool:
    """A closed UDP transport leaves the session looking ready; only the transport tells."""
    protocol = getattr(getattr(session, "stream", None), "_protocol", None)
    transport = getattr(protocol, "transport", None)
    return transport is not None and not transport.is_closing()


def _make_receiver(box: FrameBox):
    from ps5_remoteplay_mcp.vendor.pyremoteplay.receiver import AVReceiver

    class VideoOnlyReceiver(AVReceiver):
        """Decodes video straight to BGR and hands the newest frame to the box; drops audio."""

        def __init__(self) -> None:
            super().__init__()
            self.video_format = "bgr24"

        def _get_audio_codec(self, header: bytes) -> None:
            return None

        def handle_audio_data(self, buf: bytes) -> None:
            return None

        def handle_audio(self, frame) -> None:
            return None

        def handle_video(self, frame) -> None:  # called from the library's decoder thread
            box.put(frame)

        def close(self) -> None:
            # The library calls decoder.close(), which current PyAV no longer has.
            self._video_decoder = self._audio_decoder = None

    return VideoOnlyReceiver()


class RemotePlaySource:
    def __init__(self, host: str | None = None, resolution: str = "1080p", fps: int = 30, user: str | None = None) -> None:
        cfg = paths.load_config()
        self.host = host or cfg.get("ps5_host")
        if not self.host:
            raise SourceError("no PS5 address saved; run: tarjim source setup")
        self.user = user or cfg.get("ps5_user")
        self.resolution = resolution
        self.fps = 60 if int(fps) >= 60 else 30
        self.box = FrameBox()
        self.reconnects = 0
        self.connects = 0
        self.last_error: str | None = None
        self.state = "starting"
        self._size = (0, 0)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._thread_main, name="rp-source", daemon=True)
        self._thread.start()

    # -- session thread -----------------------------------------------------

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as exc:  # a crash here must surface to the consumer, not vanish
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.state = "failed"
        finally:
            self.box.close()

    async def _run(self) -> None:
        from ps5_remoteplay_mcp.vendor.pyremoteplay import RPDevice

        ps5._quiet_vendor_logs()
        device = RPDevice(self.host)
        while not self._stop.is_set():
            try:
                await self._session_once(device)
            except SourceError as exc:
                self.last_error = str(exc)
            except Exception as exc:
                # The library raises plain network errors too (a reset connection while
                # starting a session, for instance). A drop is a drop: reconnect.
                self.last_error = f"{type(exc).__name__}: {str(exc)[:160]}"
            finally:
                try:
                    device.disconnect()
                except Exception as exc:  # a half-open session must not stop the reconnect loop
                    self.last_error = self.last_error or f"{type(exc).__name__}: {str(exc)[:160]}"
            if self._stop.is_set():
                break
            self.state = "reconnecting"
            await asyncio.sleep(RECONNECT_PAUSE_S)

    async def _session_once(self, device) -> None:
        status = await device.async_get_status()
        if not status:
            raise SourceError(f"no answer from the console at {self.host}")
        if not device.is_on:
            raise SourceError("the console is in rest mode")
        profiles = ps5.load_profiles()
        users = device.get_users(profiles=profiles)
        if not users:
            raise SourceError("this laptop is not linked to the console; run: tarjim source setup")
        user = self.user if self.user in users else users[0]
        receiver = _make_receiver(self.box)
        session = device.create_session(
            user,
            profiles=profiles,
            loop=asyncio.get_running_loop(),
            receiver=receiver,
            resolution=self.resolution,
            fps=self.fps,
            quality="default",
            codec="h264",
            hdr=False,
        )
        if session is None:
            raise SourceError("could not create a session (profile not found)")
        # Detach the controller object the library attached: with no session it
        # cannot send anything even if something called it by mistake.
        device.controller.disconnect()
        self.state = "connecting"
        if not await device.connect():
            raise SourceError(f"session refused: {getattr(session, 'error', '') or 'connect failed'}")
        if not await device.async_wait_for_session(timeout=20):
            raise SourceError(f"session did not become ready: {getattr(session, 'error', '') or 'timeout'}")
        first_seq = self.box.seq
        deadline = time.monotonic() + 15
        while self.box.seq == first_seq:
            if time.monotonic() > deadline or session.is_stopped:
                raise SourceError("connected but no video frames arrived")
            await asyncio.sleep(0.05)
        if self.connects:
            self.reconnects += 1
        self.connects += 1
        self.state = "streaming"
        self.last_error = None
        while not self._stop.is_set():
            await asyncio.sleep(0.2)
            if session.is_stopped or not session.is_ready or not _stream_open(session):
                raise SourceError(f"session ended: {getattr(session, 'error', '') or 'stream closed'}")
            last = self.box.last_arrival
            if last is not None and time.monotonic() - last > STALL_S:
                raise SourceError(f"no video for {STALL_S:.0f} s")

    # -- FrameSource ----------------------------------------------------------

    def frames(self) -> Iterator[tuple[np.ndarray, float, int]]:
        while not self._stop.is_set():
            item = self.box.get(timeout=0.5)
            if item is None:
                if self.box.closed:
                    if self.last_error and self.state == "failed":
                        raise SourceError(self.last_error)
                    return
                continue
            av_frame, t_capture, seq = item
            frame = av_frame.to_ndarray()  # already bgr24
            self._size = (frame.shape[1], frame.shape[0])
            yield frame, t_capture, seq

    def info(self) -> SourceInfo:
        return SourceInfo(
            BACKEND, self._size[0], self._size[1], self.box.fps(), delay_ms=None,
            reconnects=self.reconnects, dropped=self.box.dropped,
        )

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self.box.close()
