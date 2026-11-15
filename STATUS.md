# Tarjim status

Last update: 2026-11-15

## Milestones

| Milestone | State | How it was verified |
| --- | --- | --- |
| M0 Preflight | **Partly done** | Hardware detected; uv, Python 3.12.16, adb 37.0.1, JDK 17.0.21, Android cmdline-tools, Gradle 9.9.1 installed in `.tools/` with checksums verified. `tarjim doctor` runs. Open: Android SDK packages (licence), M0 questions to the user. |
| M1 TV overlay | **Code written, laptop side tested, TV app not built yet** | `pytest`: 60 passed (framing, fragmented and malformed frames, reconnect, TTL, keep, clear, 1000 ms watchdog, atomic multi-layer show, seq ordering, adb allowlist, screencap self-check logic against FakeTv). The Kotlin app has never been compiled or run. |
| M2 Picture source | Not started | |
| GATE 1 (T1, T2) | Waiting for M1 + M2 | |
| M3 to M7 | Not started | |

## Open issues

1. **Android SDK licences not accepted.** `platforms;android-36` and
   `build-tools;36.0.0` cannot be installed until the user accepts Google's
   SDK licences (`tarjim sdk install`). Until then the TV app cannot be built,
   so the AGP 9.5.1 / Gradle 9.9.1 / compileSdk 36 combination and all Kotlin
   code are unverified.
2. **M0 questions unanswered**: TV IP, PS5 wired or Wi-Fi, HDR on or off,
   which games, dialogue screenshots in `samples/`.
3. Nothing has touched the TV yet: `docs/adb-log.md` does not exist because
   no adb command has been run against a device.
4. Pillow on this machine has no RAQM; M3 must shape Arabic with HarfBuzz.

## Benchmarks

None measured yet (the section 8 table is filled in at M3).
