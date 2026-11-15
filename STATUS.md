# Tarjim status

Last update: 2026-11-15

## Milestones

| Milestone | State | How it was verified |
| --- | --- | --- |
| M0 Preflight | **Partly done** | Hardware detected; uv, Python 3.12.16, adb 37.0.1, JDK 17.0.21, Android cmdline-tools, Gradle 9.9.1 installed in `.tools/` with checksums verified. `tarjim doctor` runs and reports the open points. Open: Android SDK packages (licence), M0 questions to the user. |
| M1 TV overlay | **Code written; laptop side tested; TV app never built or run** | `pytest` (protocol, FakeTv, TvLink, adb allowlist, screencap self-check logic). The Kotlin app has not been compiled: blocked on the SDK licence. Nothing has been sent to the TV. |
| M2 Picture source | **Code written; tested without the console only** | `pytest` (FrameBox, file source with images and a generated video). `tarjim source test --backend file` ran. The Remote Play library imports on Python 3.12.16 / PyAV 19.0.2, and LAN discovery found the PS5 (192.168.172.109, rest mode). No Remote Play session has been attempted: needs the second PSN account, sign-in and PIN. |
| GATE 1 (T1, T2) | Waiting for M1 + M2 to be finished with the user | Steps are in `docs/TESTS-AR.md`. |
| M3 to M7 | Not started | |

Automated tests: 67 passed (`uv run pytest`, in `laptop/`).

## Open issues

1. **Android SDK licences not accepted.** `platforms;android-36` and
   `build-tools;36.0.0` cannot be installed until the user accepts Google's
   SDK licences (`tarjim sdk install`). Until then the TV app cannot be built,
   so the AGP 9.5.1 / Gradle 9.9.1 / compileSdk 36 combination and all Kotlin
   code are unverified.
2. **M0 questions unanswered**: TV IP, PS5 wired or Wi-Fi, HDR on or off,
   which games, dialogue screenshots in `samples/`.
3. **PS5 not linked**: second PSN account, sign-in on Sony's page, PIN
   (`tarjim source setup`).
4. **Unverified until a real session runs**: that the firmware accepts the
   connection, that a session with zero controller feedback stays alive,
   25 fps at 1080p for 30 minutes, reconnect within 5 s.
5. Nothing has touched the TV yet: `docs/adb-log.md` does not exist because
   no adb command has been run against a device.
6. Pillow on this machine has no RAQM; M3 must shape Arabic with HarfBuzz.

## Benchmarks

None measured yet (the section 8 table is filled in at M3).
