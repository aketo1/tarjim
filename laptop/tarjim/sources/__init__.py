"""Frame sources: where the pipeline gets the game picture from."""

from .base import FrameBox, FrameSource, SourceError, SourceInfo

__all__ = ["FrameBox", "FrameSource", "SourceError", "SourceInfo", "open_source"]


def open_source(backend: str, **kwargs) -> FrameSource:
    if backend == "file":
        from .file import FileSource

        return FileSource(kwargs["path"], fps=kwargs.get("fps", 30.0), loop=kwargs.get("loop", False))
    if backend == "rp-pyremoteplay":
        from .remoteplay import RemotePlaySource

        return RemotePlaySource(
            host=kwargs.get("host"), resolution=kwargs.get("resolution", "1080p"), fps=kwargs.get("fps", 30)
        )
    raise SourceError(f"unknown backend {backend!r}")
