"""Phone control: who may reach the app from the home network, and how they pair.

Off by default. When the user switches it on, the app also listens on the
home network (port 47901) and answers a discovery broadcast (UDP 47902).
A phone becomes trusted by sending the 6-digit code shown on the laptop
once; it then holds a random token, of which only the hash is stored here.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import socket
import threading
import time

from .. import paths

REMOTE_PORT = 47901
DISCOVERY_PORT = 47902
DISCOVERY_ASK = b"TARJIM?"
MAX_TRIES = 6  # wrong codes before the code is replaced and pairing pauses
LOCK_SECONDS = 60.0
MAX_DEVICES = 8


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def lan_ip() -> str | None:
    """This laptop's address on the home network (no packet is sent)."""
    cfg = paths.load_config()
    for target in (cfg.get("tv_ip"), "192.168.1.1", "10.0.0.1"):
        if not target:
            continue
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((str(target).split(":")[0], 9))
                ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
        except OSError:
            continue
    return None


class RemoteAccess:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.pin = self._new_pin()
        self._bad = 0
        self._locked_until = 0.0
        self.on_change = None  # callback() after pairing or removal, to refresh the laptop's screen

    @staticmethod
    def _new_pin() -> str:
        return f"{secrets.randbelow(1_000_000):06d}"

    # -- stored state ---------------------------------------------------------

    @staticmethod
    def _state() -> dict:
        phone = paths.load_config().get("phone")
        return phone if isinstance(phone, dict) else {}

    @staticmethod
    def _save(phone: dict) -> None:
        cfg = paths.load_config()
        cfg["phone"] = phone
        paths.save_config(cfg)

    @property
    def enabled(self) -> bool:
        return bool(self._state().get("enabled"))

    def set_enabled(self, on: bool) -> None:
        with self._lock:
            phone = self._state()
            phone["enabled"] = bool(on)
            self._save(phone)
            if on:
                self.pin = self._new_pin()

    def devices(self) -> list[dict]:
        return [{"id": d["id"], "name": d["name"], "added": d["added"]} for d in self._state().get("devices", [])]

    def forget(self, device_id: str) -> None:
        with self._lock:
            phone = self._state()
            phone["devices"] = [d for d in phone.get("devices", []) if d.get("id") != device_id]
            self._save(phone)

    # -- pairing and checking ---------------------------------------------------

    def pair(self, pin: str, name: str) -> str:
        """Returns a new token, or raises ValueError with an Arabic reason."""
        with self._lock:
            now = time.monotonic()
            if now < self._locked_until:
                raise ValueError("محاولات كثيرة. انتظر دقيقة ثم اكتب الرمز الجديد اللي على اللابتوب.")
            if not secrets.compare_digest(str(pin).strip(), self.pin):
                self._bad += 1
                if self._bad >= MAX_TRIES:
                    self._bad = 0
                    self._locked_until = now + LOCK_SECONDS
                    self.pin = self._new_pin()
                raise ValueError("الرمز مو صحيح. شوف الرمز في ترجِم على اللابتوب ‹ الجوال.")
            self._bad = 0
            token = secrets.token_urlsafe(32)
            phone = self._state()
            devices = phone.get("devices", [])
            clean = "".join(ch for ch in str(name) if ch.isprintable())[:40].strip() or "جوال"
            devices.append({"id": secrets.token_hex(4), "name": clean, "hash": _hash(token), "added": time.time()})
            phone["devices"] = devices[-MAX_DEVICES:]
            self._save(phone)
            self.pin = self._new_pin()  # one code pairs one phone
        if self.on_change is not None:
            self.on_change()
        return token

    def allowed(self, token: str | None) -> bool:
        if not token or not self.enabled:
            return False
        wanted = _hash(token)
        return any(secrets.compare_digest(wanted, d.get("hash", "")) for d in self._state().get("devices", []))

    def view(self) -> dict:
        ip = lan_ip()
        base = f"http://{ip}:{REMOTE_PORT}" if ip else None
        return {
            "enabled": self.enabled, "ip": ip, "port": REMOTE_PORT, "url": base, "pin": self.pin,
            "pair_url": f"{base}/?pair={self.pin}" if base else None, "devices": self.devices(),
            "apk": paths.PHONE_APK.exists(),
        }


def qr_svg(text: str) -> bytes:
    """A QR code as an SVG picture (dark modules only, transparent background)."""
    import io

    import segno

    out = io.BytesIO()
    segno.make(text, error="m").save(out, kind="svg", scale=8, border=2, dark="#111114", light="#ffffff",
                                     xmldecl=False, svgns=True, nl=False)
    return out.getvalue()


def serve_discovery(stop: threading.Event, access: RemoteAccess) -> None:
    """Answer "is Tarjim here?" broadcasts from the phone app. Runs until `stop` is set."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", DISCOVERY_PORT))
        sock.settimeout(1.0)
    except OSError:
        return  # port taken: the phone can still be given the address by hand
    reply = json.dumps({"tarjim": 1, "name": socket.gethostname(), "port": REMOTE_PORT}).encode("utf-8")
    with sock:
        while not stop.is_set():
            try:
                data, addr = sock.recvfrom(64)
            except TimeoutError:
                continue
            except OSError:
                break
            if data.strip() == DISCOVERY_ASK and access.enabled:
                try:
                    sock.sendto(reply, addr)
                except OSError:
                    pass
