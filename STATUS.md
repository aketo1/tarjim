# Tarjim status

Last update: 2026-11-16. The full picture is in `docs/REPORT.md` (section 14 is the newest).

## Milestones

| Milestone | State | How it was verified |
| --- | --- | --- |
| M0 Preflight | Done | Toolchain in `.tools/` with checksums; user answered the questions and supplied two samples |
| M1 TV overlay | Done | App built (AGP 9.5.1, Gradle 9.9.1), installed on the TCL TV, protocol tests pass, patterns acked as drawn |
| M2 Picture source | Done | Receive-only Remote Play: 1920x1080 at 30 fps, 0 reconnects in 15-minute sessions |
| GATE 1 | Passed by the user | T1: patterns A and B visible over the game, remote works. T2: controller, sound and 4K HDR output unchanged while the copy runs |
| M3 Offline core | Done | Detection, OCR, local translation, renderer, fake TV, `preview`, automated tests |
| M4 Live end to end | Done, in `replace` mode | Played live in Red Dead Redemption 2; user reports position, look and speed as very good |
| GATE 2 (T3 to T5) | Informally passed | The user judged position, look and controller feel during live play; no formal T3 boxes test, no calibration tools built |
| M5 Robustness | Partly | Reading-time hold on a plate, split-line rejoin, fixed font size, reconnect. Not built: `frost`/`auto` modes, boxed-subtitle handling, record/replay |
| M6 Gemini | Tried and removed | Slower than local live (1.2 s vs under 0.1 s) and rate-limited on the free tier; see `DECISIONS.md` |
| M7 Finish | Mostly | Desktop program `Tarjim.exe` with its own interface and guide; still no `README-AR.md` |
| 0.2 polish | Done | Own executable (taskbar shows Tarjim), no console flashes, redesigned laptop and TV interfaces, phone control + Android app, glossary names kept right (14 of 59 wrong -> 0), user fixes. 114 tests pass |

## Live numbers (15-minute RDR2 session, laptop on mains)

100 lines shown; first sight of the English to Arabic on the TV: median 150 ms,
p90 243 ms; translation median 96 ms; stream 30 fps, 0 reconnects.

## Open issues

1. Remote Play's own delay (PS5 to laptop) is unmeasured (needs a slow-motion film of the TV: test T6).
2. The 30-minute stream criterion was never run in one piece; several 15-minute sessions were clean.
3. Fill colour under HDR is unverified by photo; the user has not reported a mismatch.
4. Only RDR2 has been played live. Other games need their own profile (glossary, settle time).
5. The laptop must be on mains: on battery translation was about 4 times slower.
6. The phone app was built but never run on a real phone; the firewall prompt and a phone reaching the laptop are untested.
7. The name handling and the new TV status screen have not been seen in a live session yet (PS5 was off).
