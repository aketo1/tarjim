"""Xbox as a picture source (experimental: written from a reference client, not yet run against a console).

How the Xbox differs from the PS5: Microsoft's "Remote Play" (home streaming)
is WebRTC. The program's own window is a browser (Edge WebView2), which speaks
WebRTC natively, so the window receives the stream with the open-source
`xbox-xcloud-player` library (MIT, bundled as `app/web/xCloudPlayer.min.js`)
and hands frames to this module over the local HTTP server. This module holds:

- the Microsoft sign-in (device-code flow: the user types a short code at
  microsoft.com/link; no password ever passes through this program) and the
  chain of tokens that ends in a streaming token. Ported from `xal-node` 1.1.5
  (`dist/msal.js`), the sign-in library of the same reference project;
- the frame hand-off (`XboxSource`), a `FrameSource` like the others;
- nothing that sends controller input: the page opens the protocol's input
  channel because the console requires it, and never puts a button in it.

Tokens are secrets and live in ~/.tarjim/xbox-tokens.json.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Iterator

import numpy as np

from .. import paths
from .base import FrameBox, SourceError, SourceInfo

CLIENT_ID = "1f907974-e22b-4810-a9de-d9647380c97e"  # the public client xal-node uses
SCOPE = "xboxlive.signin openid profile offline_access"
TOKEN_FILE = paths.HOME_DIR / "xbox-tokens.json"
_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36")


class XboxError(SourceError):
    pass


def _post(host: str, path: str, body: bytes, headers: dict, timeout: float = 15.0) -> dict:
    req = urllib.request.Request(f"https://{host}{path}", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise XboxError(f"{host}{path} answered {exc.code}: {detail}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise XboxError(f"cannot reach {host}: {exc}") from exc


def _form(fields: dict) -> bytes:
    return urllib.parse.urlencode(fields).encode("ascii")


_FORM = {"Content-Type": "application/x-www-form-urlencoded"}


class XboxAuth:
    """The sign-in state and the token chain. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._gs: dict | None = None  # {"token", "host", "until"}
        self.link_state = "idle"  # idle | waiting | linked | failed
        self.link_error = ""
        self.user_code = ""
        self.verification_uri = ""

    # -- stored tokens ----------------------------------------------------------

    @staticmethod
    def _load() -> dict:
        try:
            return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _save(data: dict) -> None:
        paths.write_private(TOKEN_FILE, json.dumps(data))

    @property
    def linked(self) -> bool:
        return bool(self._load().get("refresh_token"))

    def forget(self) -> None:
        with self._lock:
            self._gs = None
            self.link_state = "idle"
            if TOKEN_FILE.exists():
                TOKEN_FILE.unlink()

    # -- device-code sign-in ------------------------------------------------------

    def start_link(self) -> dict:
        """Ask Microsoft for a short code; a background thread waits for the user to enter it."""
        answer = _post("login.microsoftonline.com", "/consumers/oauth2/v2.0/devicecode",
                       _form({"client_id": CLIENT_ID, "scope": SCOPE}), _FORM)
        if not answer.get("user_code") or not answer.get("device_code"):
            raise XboxError("Microsoft did not return a sign-in code")
        with self._lock:
            self.user_code = answer["user_code"]
            self.verification_uri = answer.get("verification_uri", "https://www.microsoft.com/link")
            self.link_state, self.link_error = "waiting", ""
        threading.Thread(target=self._wait_for_user, name="tarjim-xbox-link", daemon=True,
                         args=(answer["device_code"], float(answer.get("interval", 5)), float(answer.get("expires_in", 900)))).start()
        return {"code": self.user_code, "url": self.verification_uri}

    def _wait_for_user(self, device_code: str, interval: float, expires: float) -> None:
        deadline = time.monotonic() + expires
        body = _form({"grant_type": "urn:ietf:params:oauth:grant-type:device_code", "client_id": CLIENT_ID,
                      "device_code": device_code})
        while time.monotonic() < deadline and self.link_state == "waiting":
            time.sleep(max(2.0, interval))
            try:
                token = _post("login.microsoftonline.com", "/consumers/oauth2/v2.0/token", body, _FORM)
            except XboxError as exc:
                if "authorization_pending" in str(exc) or "slow_down" in str(exc):
                    continue
                self.link_state, self.link_error = "failed", str(exc)
                return
            if token.get("refresh_token"):
                self._save({"refresh_token": token["refresh_token"]})
                with self._lock:
                    self._gs = None
                    self.link_state = "linked"
                return
        if self.link_state == "waiting":
            self.link_state, self.link_error = "failed", "the code expired"

    # -- the token chain ------------------------------------------------------------

    def _access_token(self) -> str:
        stored = self._load()
        if not stored.get("refresh_token"):
            raise XboxError("not linked to a Microsoft account")
        token = _post("login.microsoftonline.com", "/consumers/oauth2/v2.0/token",
                      _form({"client_id": CLIENT_ID, "grant_type": "refresh_token",
                             "refresh_token": stored["refresh_token"], "scope": SCOPE}), _FORM)
        if token.get("refresh_token"):
            self._save({"refresh_token": token["refresh_token"]})  # Microsoft rotates it
        if not token.get("access_token"):
            raise XboxError("Microsoft did not return an access token")
        return token["access_token"]

    def streaming(self) -> dict:
        """{"token": gsToken, "host": the region's API host}. Cached until shortly before it expires."""
        with self._lock:
            if self._gs and self._gs["until"] > time.time() + 120:
                return self._gs
            xbl = {"x-xbl-contract-version": "1", "Cache-Control": "no-cache", "Content-Type": "application/json",
                   "Origin": "https://www.xbox.com", "Referer": "https://www.xbox.com/"}
            user = _post("user.auth.xboxlive.com", "/user/authenticate", json.dumps({
                "Properties": {"AuthMethod": "RPS", "RpsTicket": "d=" + self._access_token(), "SiteName": "user.auth.xboxlive.com"},
                "RelyingParty": "http://auth.xboxlive.com", "TokenType": "JWT"}).encode("utf-8"), xbl)
            xsts = _post("xsts.auth.xboxlive.com", "/xsts/authorize", json.dumps({
                "Properties": {"SandboxId": "RETAIL", "UserTokens": [user["Token"]]},
                "RelyingParty": "http://gssv.xboxlive.com/", "TokenType": "JWT"}).encode("utf-8"),
                {**xbl, "Accept": "*/*", "ms-cv": "0", "User-Agent": _BROWSER})
            home = _post("xhome.gssv-play-prod.xboxlive.com", "/v2/login/user",
                         json.dumps({"token": xsts["Token"], "offeringId": "xhome"}).encode("utf-8"),
                         {"Content-Type": "application/json", "Cache-Control": "no-store, must-revalidate, no-cache",
                          "x-gssv-client": "XboxComBrowser"})
            regions = (home.get("offeringSettings") or {}).get("regions") or []
            region = next((r for r in regions if r.get("isDefault")), regions[0] if regions else None)
            if not home.get("gsToken") or not region or not region.get("baseUri"):
                raise XboxError("Xbox did not return a streaming token")
            host = urllib.parse.urlparse(region["baseUri"]).netloc or region["baseUri"]
            self._gs = {"token": home["gsToken"], "host": host,
                        "until": time.time() + float(home.get("durationInSeconds", 3600))}
            return self._gs

    def proxy(self, method: str, path: str, body: bytes | None, device_info: str | None) -> tuple[int, bytes]:
        """Forward one of the page's streaming API calls (/v5/..., /v6/...) to Xbox with the token added."""
        gs = self.streaming()
        headers = {"Authorization": "Bearer " + gs["token"], "Content-Type": "application/json; charset=utf-8",
                   "Accept": "application/json"}
        if device_info:
            headers["X-MS-Device-Info"] = device_info
        req = urllib.request.Request(f"https://{gs['host']}{path}", data=body if method == "POST" else None,
                                     headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except (urllib.error.URLError, OSError) as exc:
            raise XboxError(f"cannot reach Xbox: {exc}") from exc

    def consoles(self) -> list[dict]:
        status, body = self.proxy("GET", "/v6/servers/home", None, None)
        if status != 200:
            raise XboxError(f"listing consoles answered {status}")
        out = []
        for item in json.loads(body.decode("utf-8")).get("results", []):
            out.append({"id": item.get("serverId"), "name": item.get("deviceName") or "Xbox",
                        "type": item.get("consoleType") or "", "power": item.get("powerState") or "",
                        "away": bool(item.get("outOfHomeWarning"))})
        return out


class XboxSource:
    """Frames posted by the program's window (JPEG pictures of the stream), newest only."""

    backend = "xbox-webrtc"

    def __init__(self) -> None:
        self._box = FrameBox()
        self._size = (0, 0)
        self.last_error: str | None = None
        self.state = "starting"  # what the page last reported: starting | connected | closed | failed

    def push_jpeg(self, data: bytes) -> bool:
        import cv2

        frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            return False
        if frame.shape[:2] != (1080, 1920):  # the pipeline's thresholds are tuned at 1080p
            frame = cv2.resize(frame, (1920, 1080), interpolation=cv2.INTER_LINEAR)
        self._size = (frame.shape[1], frame.shape[0])
        self._box.put(frame)
        return True

    def frames(self) -> Iterator[tuple[np.ndarray, float, int]]:
        waited = 0.0
        while not self._box.closed:
            item = self._box.get(timeout=1.0)
            if item is None:
                waited += 1.0
                if self.state == "failed":
                    return
                if waited >= 45.0 and self._box.seq == 0:
                    self.last_error = self.last_error or "ما وصلت صورة من الإكس بوكس."
                    return
                continue
            waited = 0.0
            yield item  # type: ignore[misc]

    def info(self) -> SourceInfo:
        return SourceInfo(self.backend, self._size[0], self._size[1], self._box.fps(), None, 0, self._box.dropped)

    def close(self) -> None:
        self._box.close()
