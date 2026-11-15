"""Finding the PS5 and linking this laptop to it (second PSN account + PIN).

Uses the patched pyremoteplay vendored inside the `ps5-remoteplay-mcp`
package. The PSN password never passes through this code: the user signs in
on Sony's page and gives us the redirect URL, which holds a one-time code.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from .. import paths
from .base import SourceError

PROFILE_FILE = paths.HOME_DIR / "ps5-profiles.json"
REDIRECT_PREFIX = "https://remoteplay.dl.playstation.net/remoteplay/redirect"
_VENDOR_LOGGER = "ps5_remoteplay_mcp.vendor.pyremoteplay"


def _quiet_vendor_logs() -> None:
    # DEBUG logs of the protocol library print handshake keys; never allow them.
    vendor = logging.getLogger(_VENDOR_LOGGER)
    vendor.setLevel(max(logging.WARNING, vendor.level))


def load_profiles():
    from ps5_remoteplay_mcp.vendor.pyremoteplay.profile import Profiles

    _quiet_vendor_logs()
    paths.ensure_home()
    if not PROFILE_FILE.exists():
        paths.write_private(PROFILE_FILE, "{}")
    # The library falls back to its default path whenever it is handed an
    # empty (falsy) Profiles object, so point that default at our file too.
    Profiles.set_default_path(str(PROFILE_FILE))
    return Profiles.load(str(PROFILE_FILE))


def save_profiles(profiles) -> None:
    import json

    # Not profiles.save(): without an explicit path it writes to the library's
    # own default folder instead of ~/.tarjim.
    paths.write_private(PROFILE_FILE, json.dumps(dict(profiles.data)))


@dataclass(frozen=True)
class Found:
    host: str
    name: str
    host_type: str
    status: str
    mac: str
    firmware: str


def discover() -> list[Found]:
    from ps5_remoteplay_mcp.vendor.pyremoteplay import RPDevice

    _quiet_vendor_logs()
    devices = asyncio.run(RPDevice.async_search())
    return [
        Found(d.host, d.host_name or "", d.host_type or "", d.status_name or "", d.mac_address or "", d.system_version or "")
        for d in devices
    ]


def device_for(host: str):
    from ps5_remoteplay_mcp.vendor.pyremoteplay import RPDevice

    _quiet_vendor_logs()
    try:
        device = RPDevice(host)
    except OSError as exc:
        raise SourceError(f"bad console address {host!r}: {exc}") from exc
    if not device.get_status():
        raise SourceError(f"no answer from the console at {host}")
    return device


def linked_users(device) -> list[str]:
    profiles = load_profiles()
    if not profiles:  # an empty Profiles crashes the library's argument handling
        return []
    return device.get_users(profiles=profiles)


def login_url() -> str:
    from ps5_remoteplay_mcp.vendor.pyremoteplay.oauth import get_login_url

    return get_login_url()


def add_user_from_redirect(redirect_url: str) -> str:
    """Exchange Sony's redirect URL for the account's ID; returns the PSN name."""
    redirect_url = redirect_url.strip()
    if not redirect_url.startswith(REDIRECT_PREFIX) or "code=" not in redirect_url:
        raise SourceError("not the redirect page address (it must start with remoteplay.dl.playstation.net and contain code=)")
    profiles = load_profiles()
    profile = profiles.new_user(redirect_url, save=False)
    if profile is None:
        raise SourceError("Sony rejected the sign-in code (codes expire within minutes); sign in again")
    save_profiles(profiles)
    return profile.name


def pending_users() -> list[str]:
    """Signed-in PSN users not linked to any console yet."""
    return [u.name for u in load_profiles().users if not u.hosts]


def link(device, user: str, pin: str) -> None:
    pin = pin.strip().replace(" ", "")
    if not (pin.isdigit() and len(pin) == 8):
        raise SourceError("the PIN must be 8 digits")
    profiles = load_profiles()
    if device.register(user, pin, profiles=profiles, save=False) is None:
        raise SourceError("the console rejected the PIN (it changes every few minutes; get a new one)")
    save_profiles(profiles)
