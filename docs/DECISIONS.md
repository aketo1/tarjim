# Decisions

Non-obvious choices and the evidence behind them. Newest last.

## M0 (2026-11-15)

- **Laptop detected**: Windows 11 Pro 26200, Intel i5-12450H (8 cores / 12
  threads), Intel UHD graphics only, 7.7 GB RAM, 1920x1200 screen. No
  discrete GPU, little RAM: the `local-llm` engine stays off, and the Android
  build runs without a Gradle daemon and with a 1.5 GB heap.
- **Toolchain lives in `.tools/` inside the repo** (git-ignored), not
  installed system-wide: adb platform-tools 37.0.1, Temurin JDK 17.0.21,
  Android command-line tools 15859902, Gradle 9.9.1. No admin rights needed,
  and deleting the folder removes everything. Only `uv` (0.13.8) was installed
  per-user through winget.
- **Downloads verified**: command-line tools zip SHA-256 matched the value
  published on developer.android.com/studio; Gradle 9.9.1 zip and wrapper jar
  matched services.gradle.org/versions/current.
- **Python 3.12.16 through uv**, lock file `laptop/uv.lock`. The machine only
  had 3.13 and 3.14.
- **Android Gradle Plugin 9.5.1 + Gradle 9.9.1 + JDK 17 + compileSdk 36 +
  build-tools 36.0.0.** developer.android.com/build/releases/gradle-plugin
  (read 2026-11-15): AGP 9.5 needs Gradle >= 9.6.0, build-tools 36.0.0, JDK
  17, max API 37. AGP 9 has built-in Kotlin, so no Kotlin plugin is applied.
  NOT YET VERIFIED BY A BUILD (see STATUS.md).
- **TV app uses only the Android framework** (no androidx, no third-party
  libraries): smaller APK, nothing to license, less RAM on the TV.
- **Pillow 13.0.0 on this Windows machine reports no RAQM**
  (`PIL.features.check("raqm")` is False). Per the brief, M3 will shape
  Arabic with HarfBuzz (`uharfbuzz` + FreeType) instead.

## M1 (2026-11-15)

- **adb goes through an allowlist** (`laptop/tarjim/adb.py`): only the command
  shapes named in the safety rules match; anything else raises before adb
  starts. Tests cover both lists.
- **Layer cap is per window** (4 in A, 4 in B) so `tv test` can show A and B
  together; a 1920x480 ARGB layer is 3.7 MB, so the worst case is ~30 MB.
- **`tv revert` removes only our entry** from the current
  `enabled_accessibility_services` instead of writing back the saved value,
  so services the user enabled after setup survive. The saved value is kept
  as a backup in `~/.tarjim/tv-state.json`.
- **Service stop uses `am stopservice`**, never `am force-stop`: a force-stop
  makes Android drop the app's accessibility service from the enabled list.
- **TV timestamps use `SystemClock.elapsedRealtime`** (monotonic), mapped to
  laptop time with the ping/pong offset.
- **`OverlayService` is exported without a permission** (needed for adb
  start). Any app on the TV could start it; accepted for a personal sideload.

## M2 (2026-11-15)

- **Backend chosen to try first: `rp-pyremoteplay`**, through the PyPI
  package `ps5-remoteplay-mcp==0.2.2` (GPL-3.0; sdist SHA-256
  `c00b3b59...253160` checked against PyPI), importing only its vendored,
  patched `pyremoteplay` 0.7.6. Its NOTICE.md lists the fixes the brief
  mentions (pyee, PyAV flag names, client version 9, thread-safe sends, numpy
  FEC). Installed as a dependency rather than copied, so no GPL source sits in
  this repo. Its MCP server, daemon and gamepad code are never imported.
- **No controller input, by construction.** Read in the vendored
  `controller.py`: feedback packets are sent only by `Controller.start()`'s
  worker (and only when the stick state changes) or by explicit
  `button`/`stick` calls. `RemotePlaySource` never calls `start()` and
  detaches the controller object right after `create_session`. Session
  keep-alive is the separate heartbeat in `session.py`. Whether the PS5 keeps
  a session with zero feedback packets alive is NOT yet verified (needs the
  console; part of `source test` / T2).
- **Profiles are written by our own code** to `~/.tarjim/ps5-profiles.json`:
  the library's `Profiles.save()` without a path writes to its own default
  folder (`util.write_profiles`), ignoring `set_default_path`.
- **Library logging capped at WARNING**: its DEBUG output prints handshake
  keys.
- **Stream request: 1080p, 30 fps, H.264, SDR, video only** (audio packets
  are dropped before decoding). 30 fps is enough to read subtitles and halves
  the decode load on a laptop with no discrete GPU.
- **Newest-frame hand-off (`FrameBox`)**: the consumer always gets the latest
  frame and skipped ones are counted, so a slow pipeline stage never builds a
  backlog (which would add delay to the Arabic).
- **Console found by discovery**: PS5 "PS5-637" at 192.168.172.109, system
  version field `14220000`, in rest mode at the time (2026-11-15).
