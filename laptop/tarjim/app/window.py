"""The program's own desktop window (pywebview on Edge WebView2) and its manners:
a title bar in the app's colour, remembered size and place, a polite question
before closing a running session, and coming to the front when started twice."""

from __future__ import annotations

import sys
from pathlib import Path

from .. import paths

TITLE = "ترجِم"
BACKGROUND = "#0a0b0f"
DEFAULT_SIZE = (1240, 860)
MIN_SIZE = (980, 660)

_window = None


def _hwnd() -> int | None:
    if _window is None or sys.platform != "win32":
        return None
    try:
        return int(_window.native.Handle.ToInt64())
    except Exception:
        import ctypes

        return ctypes.windll.user32.FindWindowW(None, TITLE) or None


def _style_title_bar() -> None:
    """Windows 11: paint the title bar and border in the app's background colour."""
    hwnd = _hwnd()
    if not hwnd:
        return
    import ctypes

    dwm = ctypes.windll.dwmapi
    def colour(hex_rgb: str) -> ctypes.c_int:
        r, g, b = int(hex_rgb[1:3], 16), int(hex_rgb[3:5], 16), int(hex_rgb[5:7], 16)
        return ctypes.c_int(r | (g << 8) | (b << 16))  # COLORREF is 0x00BBGGRR

    for attribute, value in (
        (20, ctypes.c_int(1)),  # DWMWA_USE_IMMERSIVE_DARK_MODE
        (35, colour(BACKGROUND)),  # DWMWA_CAPTION_COLOR
        (34, colour("#20232e")),  # DWMWA_BORDER_COLOR
        (36, colour("#f3f1ea")),  # DWMWA_TEXT_COLOR
    ):
        try:
            dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), attribute, ctypes.byref(value), ctypes.sizeof(value))
        except OSError:
            pass  # older Windows: the attribute does not exist, the default bar stays


def _fit_to_screen() -> None:
    """Keep the whole window inside the screen's work area (not under the taskbar, not off an edge).
    Works on the real window in real pixels, so display scaling cannot fool it."""
    hwnd = _hwnd()
    if not hwnd:
        return
    import ctypes
    import ctypes.wintypes as wt

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]

    user32 = ctypes.windll.user32
    user32.MonitorFromWindow.restype = ctypes.c_void_p
    if user32.IsZoomed(ctypes.c_void_p(hwnd)) or user32.IsIconic(ctypes.c_void_p(hwnd)):
        return
    rect, info = wt.RECT(), MonitorInfo()
    info.cbSize = ctypes.sizeof(info)
    monitor = user32.MonitorFromWindow(ctypes.c_void_p(hwnd), 2)  # nearest monitor
    if not user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rect)):
        return
    if not user32.GetMonitorInfoW(ctypes.c_void_p(monitor), ctypes.byref(info)):
        return
    work = info.rcWork
    w, h = rect.right - rect.left, rect.bottom - rect.top
    new_w, new_h = min(w, work.right - work.left), min(h, work.bottom - work.top)
    fits = rect.left >= work.left - 8 and rect.top >= work.top and rect.right <= work.right + 8 and rect.bottom <= work.bottom + 8
    if fits and (new_w, new_h) == (w, h):
        return
    x = work.left + (work.right - work.left - new_w) // 2
    y = work.top + (work.bottom - work.top - new_h) // 2
    user32.MoveWindow(ctypes.c_void_p(hwnd), x, y, new_w, new_h, True)


def _saved_geometry() -> dict:
    """Size and position from last time, only if that place is still on a screen."""
    import webview

    saved = paths.load_config().get("app_window")
    out = {"width": DEFAULT_SIZE[0], "height": DEFAULT_SIZE[1]}
    if not isinstance(saved, dict):
        return out
    try:
        w, h = int(saved["w"]), int(saved["h"])
        x, y = int(saved["x"]), int(saved["y"])
    except (KeyError, TypeError, ValueError):
        return out
    if w < MIN_SIZE[0] or h < MIN_SIZE[1]:
        return out
    out.update(width=w, height=h)
    try:
        screens = webview.screens
    except Exception:
        screens = []
    for s in screens:
        if s.x - 40 <= x <= s.x + s.width - 200 and s.y - 10 <= y <= s.y + s.height - 120:
            out.update(x=x, y=y)
            break
    out["maximized"] = bool(saved.get("max"))
    return out


def _remember() -> None:
    if _window is None:
        return
    try:
        w, h, x, y = int(_window.width), int(_window.height), int(_window.x), int(_window.y)
        maximized = False
        hwnd = _hwnd()
        if hwnd:
            import ctypes

            maximized = bool(ctypes.windll.user32.IsZoomed(ctypes.c_void_p(hwnd)))
            if ctypes.windll.user32.IsIconic(ctypes.c_void_p(hwnd)):
                return  # minimised: the numbers are meaningless
        cfg = paths.load_config()
        old = cfg.get("app_window") if isinstance(cfg.get("app_window"), dict) else {}
        if maximized and old:
            cfg["app_window"] = {**old, "max": True}  # keep the normal size underneath
        else:
            cfg["app_window"] = {"w": w, "h": h, "x": x, "y": y, "max": maximized}
        paths.save_config(cfg)
    except Exception:
        pass  # remembering the window is a nicety; never block closing for it


def focus() -> bool:
    """Bring the window to the front (used when the program is started a second time)."""
    if _window is None:
        return False
    try:
        _window.restore()
        _window.show()
        hwnd = _hwnd()
        if hwnd:
            import ctypes

            user32 = ctypes.windll.user32
            user32.ShowWindow(ctypes.c_void_p(hwnd), 9 if user32.IsIconic(ctypes.c_void_p(hwnd)) else 5)
            user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
            # Windows may refuse to steal focus; flashing the taskbar button is the polite fallback.
            user32.FlashWindow(ctypes.c_void_p(hwnd), True)
        return True
    except Exception:
        return False


def close() -> None:
    if _window is not None:
        try:
            _window.destroy()
        except Exception:
            pass


def run(url: str, icon: Path, may_close) -> bool:
    """Show the window and block until it is closed. Returns False when no window could be made.

    `may_close()` is asked when the user closes the window; returning False keeps it open
    (the page then shows its own question).
    """
    global _window
    try:
        import webview
    except Exception:
        return False
    try:
        geometry = _saved_geometry()
        _window = webview.create_window(
            TITLE, url, min_size=MIN_SIZE, background_color=BACKGROUND, text_select=True, **geometry
        )

        def on_closing():
            if not may_close():
                return False
            _remember()
            return True

        _window.events.before_show += lambda *_: _style_title_bar()
        _window.events.shown += lambda *_: (_style_title_bar(), _fit_to_screen())
        _window.events.closing += on_closing
        kwargs = {"icon": str(icon)} if icon.exists() else {}
        storage = paths.ensure_home() / "webview"
        try:
            webview.start(private_mode=False, storage_path=str(storage), **kwargs)
        except TypeError:  # an older pywebview without these arguments
            webview.start()
        return True
    except Exception:
        return False
    finally:
        _window = None
