# Tarjim (ترجِم): project report

Written 2026-11-15. This file is the handover for anyone, human or AI, who
will read, improve or build a user interface for this project. It describes
what exists and works today, how it was built, what was measured, what is
still missing, and the rules to follow when changing it.

> **بالعربي باختصار:** ترجِم برنامج شخصي يعرض ترجمة عربية مكان الترجمة
> الإنجليزية وأنت تلعب PS5 على تلفزيون TCL. اللابتوب ياخذ نسخة من صورة
> الـPS5، يقرأ السطر الإنجليزي، يترجمه محلياً، ويرسل العربي كصورة صغيرة
> لتطبيق على التلفزيون يرسمها فوق اللعبة. هذا الملف يشرح كل شي لأي برنامج
> ذكاء اصطناعي تبي تعطيه المشروع.

## 1. What it does

While the user plays a PS5 game on the TV, English subtitles are covered and
replaced by Arabic ones in the same place and style. The game picture and the
controller are untouched: the PS5 still feeds the TV directly over HDMI.

Status today: it works live in Red Dead Redemption 2. Measured in a 15-minute
play session: 100 lines shown, median 150 ms from the English line first
appearing in the laptop's copy of the picture to the Arabic being drawn on the
TV (90th percentile 243 ms).

## 2. The setup

| Device | Role | Details on this installation |
| --- | --- | --- |
| PS5 | Runs the game | "PS5-637", 192.168.172.109, on Wi-Fi, outputs 3840x2160 60 Hz HDR |
| TV | Shows the game and the Arabic overlay | TCL "Smart TV Pro" (C635), Google TV, Android 11 (API 30), 192.168.172.251, overlay plane 1920x1080 |
| Laptop | Does all the work | Windows 11, i5-12450H, Intel UHD graphics, 8 GB RAM. Must be on mains power |

Three data paths:

1. **PS5 to TV, HDMI.** The game. Nothing of ours sits in this path.
2. **PS5 to laptop, home network.** A video-only copy of the picture through
   Sony's Remote Play protocol (1080p, 30 fps, H.264, SDR), logged in with a
   *second* PSN account so the player's own account and controller are not
   disturbed.
3. **Laptop to TV, Wi-Fi (TCP port 47800).** Small PNG images plus where to
   draw them. A thin Android app on the TV draws them over the HDMI input.

The TV cannot read the HDMI picture (screen capture of the HDMI input returns
nothing on this TV), which is why the laptop needs its own copy.

## 3. How one subtitle line is handled

Every frame of the copy (30 per second) goes through `Pipeline.process`
(`laptop/tarjim/pipeline.py`):

1. **Detect** (`vision/detect.py`, about 4 ms). Look only at the bottom 30% of
   the frame, central 84% of the width. Build a mask of thin bright strokes:
   per-pixel minimum of R, G, B, then a white top-hat filter, then a
   threshold. Find connected blobs, keep letter-sized ones, group them into
   rows and rows into a block. Pieces of one row split by a bright background
   are rejoined. Output: a `Block` (rectangle, stroke mask, text lines).
2. **Start reading at once** (worker thread). The first time a block is seen,
   OCR and translation start in the background, before we know the line is
   stable.
3. **Track** (`vision/tracker.py`). The block is confirmed when its mask stays
   the same (IoU >= 0.9, not growing) for the settle time (30 ms for RDR2,
   60 ms default). By then the Arabic is usually ready, so the wait costs
   nothing extra.
4. **OCR** (`vision/ocr.py`, about 16 ms per line). RapidOCR's English
   recognition model on each text line, cropped using the stroke mask and
   scaled to 48 px height. Rejects things that are not speech (interface
   labels such as "PS5", short all-caps labels, non-Latin text, low
   confidence).
5. **Translate** (`translate.py`, about 75 to 95 ms). Cache first (SQLite,
   under 2 ms). Otherwise the local model, sentence by sentence. Then the
   game's glossary of names and Arabic clean-up (Arabic punctuation, no
   brackets around names, no short-vowel marks).
6. **Render** (`vision/render.py`, `vision/arabic.py`, about 8 ms). Two images:
   - `fill`: the estimated background colour, only on the grown English letter
     strokes (transparent elsewhere). It hides the English without a box.
   - `text`: the Arabic, shaped with HarfBuzz and drawn with FreeType, in the
     colour of the English letters, with a soft drop shadow, centred on the
     English block, bottom baseline kept.
7. **Send** (`tvlink.py`). One `show` message with both PNGs; the TV draws them
   in the same frame and acknowledges with timestamps (about 37 ms).
8. **While the line is on screen**: the `fill` is re-made from the newest
   frame about 12 times per second so it follows the moving scene; the `text`
   is kept alive without resending pixels.
9. **When the English leaves**: if the Arabic has not had its reading time
   yet (about 15 characters per second, between 1.6 and 6 seconds), it stays
   on a dark translucent plate until that time is up, or until the next line
   replaces it. Otherwise everything is cleared.

Fail-safe: every layer on the TV has a 700 ms time-to-live and the TV clears
everything if it hears nothing for 1000 ms. If the laptop program stalls,
crashes or loses Wi-Fi, the Arabic disappears by itself within a second.

## 4. Repository map

```
tarjim/
  STATUS.md             milestone status (partly out of date; this report is newer)
  docs/
    REPORT.md           this file
    DECISIONS.md        every non-obvious choice, with the evidence behind it
    PROTOCOL.md         laptop <-> TV wire protocol v1
    TESTS-AR.md         the manual tests the user ran (Arabic)
    LICENSES.md         licence of everything used
    adb-log.md          every adb command run against the TV
  laptop/               Python 3.12 package "tarjim" + tests (uv project)
  tv-app/               Android app (Kotlin, Gradle), package dev.tarjim.tv
  profiles/             one YAML file per game (glossary, settle time, font size)
  fonts/                Harmattan, Noto Naskh Arabic, Noto Sans Arabic, Noto Sans (OFL)
  samples/              the user's screenshots + expected text; tv-photos/ (not in git)
  models/               translation models, about 1.1 GB (not in git)
  out/                  previews, session logs (not in git)
  .tools/               adb, JDK 17, Android SDK, Gradle (not in git)
```

Private files outside the repo, in `C:\Users\<user>\.tarjim\`:
`config.json` (TV address, PS5 address, PSN user name, remembered font sizes),
`ps5-profiles.json` (Remote Play registration keys: treat as a secret),
`tv-state.json` (backup of the TV settings changed by setup),
`translations.sqlite` (translation cache).

### Laptop modules (`laptop/tarjim/`)

| File | What it holds |
| --- | --- |
| `cli.py` | The `tarjim` command and its sub-commands |
| `run_cli.py` | `tarjim run` (live) and `tarjim preview` (file + fake TV) |
| `pipeline.py` | The live loop described in section 3; timings; session log |
| `vision/detect.py` | Subtitle block detection, `mask_iou` |
| `vision/tracker.py` | Stable / still there / gone state machine |
| `vision/ocr.py` | RapidOCR wrapper, line joining, speaker split, speech filter |
| `vision/arabic.py` | Bidi runs, HarfBuzz shaping, FreeType rasterising, font fallback |
| `vision/render.py` | `make_fill`, `make_text`, `make_plate`, layout, `composite` |
| `translate.py` | Engines, sentence splitting, cache, glossary, clean-up, profiles |
| `sources/base.py` | `FrameSource` interface, `FrameBox` (newest-frame hand-off) |
| `sources/remoteplay.py` | Receive-only Remote Play session with reconnect |
| `sources/ps5.py` | Finding the PS5, PSN sign-in redirect, PIN linking |
| `sources/file.py` | Image, image folder or video as a source (tests, previews) |
| `protocol.py` | Wire protocol framing and message builders |
| `tvlink.py` | TCP client to the TV: ping, clock offset, acks, reconnect |
| `faketv.py` | Python implementation of the TV side, used by tests and preview |
| `tv.py` | `tv build / setup / test / revert` through adb |
| `adb.py` | adb wrapper that refuses anything outside an allowlist |
| `source_cli.py` | `source setup / test` |
| `bench.py` | `bench latency` |
| `doctor.py` | `doctor`: checks prerequisites |
| `paths.py` | Locations, config load/save, process priority boost |
| `patterns.py` | Test patterns A and B, screencap check |
| `say.py` | Arabic console messages |

### TV app (`tv-app/app/src/main/java/dev/tarjim/tv/`)

| File | What it holds |
| --- | --- |
| `OverlayService.kt` | Foreground service; owns the TCP server and window A |
| `OverlayA11yService.kt` | Accessibility service that reads nothing; owns window B |
| `OverlayHub.kt` | Shared layer state, the two transparent full-screen views, TTL and watchdog |
| `OverlayServer.kt` | TCP server: parses frames, decodes PNGs off the UI thread, sends acks |
| `Wire.kt` | Frame reader/writer and protocol limits |
| `MainActivity.kt` | Status screen with Start and Stop buttons |

Window A is `TYPE_APPLICATION_OVERLAY`, window B `TYPE_ACCESSIBILITY_OVERLAY`.
Both were tested visible over the HDMI input; the pipeline uses A. Both are
not focusable and not touchable, so the remote keeps working. The app uses
only the Android framework (no libraries).

## 5. Commands

Run from `laptop/` as `uv run tarjim ...` or `.venv\Scripts\tarjim.exe ...`.

| Command | Purpose |
| --- | --- |
| `tarjim doctor` | Check Python, adb, JDK, SDK, the built app, the TV |
| `tarjim sdk install` | Install Android SDK packages (the user accepts Google's licences) |
| `tarjim tv build` | Build the TV app |
| `tarjim tv setup --ip <tv>` | Install and enable the app on the TV (idempotent) |
| `tarjim tv test --seconds N` | Show test patterns A (magenta, left) and B (cyan, right) |
| `tarjim tv revert` | Remove the app and undo every TV setting it changed |
| `tarjim source setup [--redirect-url URL] [--pin N]` | Link the laptop to the PS5, one step per run |
| `tarjim source test --seconds N` | Measure the picture copy: resolution, fps, gaps |
| `tarjim preview <file>` | Run the whole pipeline on an image or video against the fake TV; saves PNGs in `out/preview/` |
| `tarjim run --profile <game>` | The real thing. Options: `--engine`, `--no-fill`, `--seconds`. Keys: `o` toggle, `q` quit |
| `tarjim bench latency` | Time every stage on this laptop |

Day-to-day use: TV on, PS5 on with the game running on the player's own
account, laptop on mains, then `tarjim run --profile rdr2`.

## 6. Configuration a user interface should expose

Everything below already exists as a file or a parameter; a UI only needs to
read and write it and start or stop `tarjim run`.

| Setting | Where | Notes |
| --- | --- | --- |
| TV address | `~/.tarjim/config.json` `tv_ip` | Set by `tv setup` |
| PS5 address, PSN user | `config.json` `ps5_host`, `ps5_user` | Set by `source setup` |
| Game profile | `profiles/<name>.yaml` | Chosen with `--profile` |
| Name glossary | profile `glossary:` | English name: Arabic spelling |
| Arabic font size | profile `font_size:` or remembered in `config.json` `font_sizes` | Measured from the first 5 lines, then fixed; 34 for RDR2 here |
| Font | profile `font:` | `harmattan` (default), `harmattan-bold`, `noto-naskh`, `noto-sans-arabic` |
| Settle time | profile `settle_ms:` | Raise for games that type text letter by letter |
| Translation engine | `--engine` or `config.json` `mt_engine` | `opus-big` (default) or `nllb-600m` |
| Cover the English or not | `--no-fill` | Arabic only, English stays visible |
| Overlay window | `config.json` `window` | `A` or `B` |
| Reading time | `reading_time_ms` in `pipeline.py` | Currently in code: 900 ms + 65 ms per character, 1.6 to 6 s |
| Detection area and thresholds | `DetectParams` in `vision/detect.py` | Currently in code; should move into the profile |
| Text style | `Style` in `vision/render.py` | Shadow offset, blur, opacity, colour; currently in code |

Suggested shape for a UI: a small local program (for example a desktop window
or a local web page served by the laptop) with a Start/Stop button, a game
picker, a live list of "English -> Arabic" lines (the pipeline already calls
`on_line(english, arabic)`), the live timings from `Pipeline.times.summary()`,
an editable glossary table, a font and size picker with the `preview` output
shown as an image, and the setup steps (`doctor`, `tv setup`, `source setup`)
as guided buttons. Call the Python functions directly rather than parsing the
console output: `run_cli.run`, `run_cli.preview`, `tv.setup`, `tv.test`,
`source_cli.setup`, `doctor.run`.

## 7. What was measured

All on this laptop, on mains power.

| Stage | Time (median) | Budget in the original brief |
| --- | --- | --- |
| Detect and track, per frame | 4 ms | 8 ms |
| OCR of a block | 16 ms live, 77 ms cold bench | 120 ms |
| Local translation (opus-big) | 96 ms live (p90 155 ms) | 250 ms |
| Render and encode | 8 ms | 20 ms |
| Send, TV decode, draw | 37 ms | 60 ms |
| Fill refresh | 2 ms each, about 12 per second | at least 10 per second |
| **First sight of the English to Arabic on the TV** | **150 ms (p90 243 ms)** | 500 ms from stable |

Picture copy: 1920x1080 at 30 fps, first frame after 4.4 s, 0 reconnects in
the 15-minute sessions. The extra delay of Remote Play itself (PS5 picture to
laptop) has not been measured; it needs a slow-motion film of the TV.

Translation models compared on 22 test lines: opus-big 148 ms, NLLB-600M
635 ms, and opus read better. Both dropped every sentence after the first
until lines were split into sentences.

Automated tests: `uv run pytest` in `laptop/`. They cover the protocol
(fragmented and malformed frames, reconnect, TTL, watchdog, ordering), the adb
allowlist, detection recall and false positives on synthetic frames, erase
completeness, OCR error rate and the user's two samples, Arabic golden images,
layout bounds, the tracker (typewriter text triggers once), translation
plumbing, and the whole pipeline end to end on the fake TV.

## 8. How it was built, and what was learned on the way

The order was: tools, TV app, picture copy, two user tests, offline core,
live run, then tuning from the user's feedback. The findings that cost time:

- **TCL blocks background apps.** The TV killed our service after 10 seconds
  and refused to bind the accessibility service, logging
  `callee_does't_have_OP_AUTO_START_permission`. Fix: `adb shell appops set
  dev.tarjim.tv APP_AUTO_START allow` (our own app only), then take our entry
  out of `enabled_accessibility_services` and put it back so the system
  retries. `tv setup` does both; `tv revert` undoes them.
- **Never `am force-stop` the app**: Android then drops its accessibility
  service from the enabled list. Use `am stopservice`.
- **The user already had another accessibility service enabled** on the TV.
  Setup appends to the list and revert removes only our entry.
- **Remote Play as a silent copy works.** With a second PSN account the
  player's controller, sound and 4K HDR output were unchanged. The library's
  controller worker is never started, so no input is ever sent; the session
  stays alive on protocol heartbeats alone.
- **The Remote Play library** is the patched `pyremoteplay` vendored inside
  the PyPI package `ps5-remoteplay-mcp` 0.2.2 (GPL-3.0). Two traps: its
  `Profiles.save()` ignores the configured path (we write the file ourselves)
  and it crashes when handed an empty profiles object.
- **Pillow on Windows has no RAQM**, so Arabic is shaped with `uharfbuzz` and
  drawn with `freetype-py`, with our own small bidi (right-to-left base,
  left-to-right runs for Latin words and numbers).
- **Speed, in order of effect**: the laptop was on battery (translation
  405 ms; on mains 75 to 96 ms); Windows gives window-less programs
  "efficiency mode" (fixed with high priority and no power throttling:
  detection 9.5 ms to 4 ms); reading started only after the line had settled
  (now it starts at first sight); numpy's channel minimum was 8 times slower
  than `cv2.min`.
- **The Arabic vanished too fast.** It appeared late and was cleared the
  moment the English left. Fixed by the reading-time hold on a dark plate.
- **Cut-off sentences** ("Mr. Mor" instead of "Mr. Morgan"): letters over a
  bright part of the scene fail the stroke test and split the line. Fixed by
  rejoining pieces of the same row.
- **Font size changed from line to line.** It was measured per line and shrunk
  for long sentences. Now it is measured over the first 5 lines, fixed, and
  remembered per game; long sentences wrap instead.
- **Gemini was tried and removed.** `gemini-3.5-flash-lite` translated clearly
  better, but took 0.85 s per line in a quiet benchmark and 1.2 s live, with
  half the lines timing out, and the free tier refused requests after about
  28 in two minutes. The local model is 10 times faster. The code and the
  dependency were deleted; the measurements are in `DECISIONS.md`.

## 9. Known limits

- **HDR.** The TV shows HDR and the copy is SDR, so the `fill` colour may not
  match the picture exactly. Not reported as a problem by the user so far.
- **Translation quality** is that of a small local model: fine for plain
  sentences, weak on slang, jokes and context. Names depend on the glossary.
- **Speaker names** drawn beside the line (for example in RDR2 cutscenes) stay
  in English.
- **Only light text** is detected (`bright-thin` model). Dark or strongly
  coloured subtitles are not found.
- **One game profile** has been tuned and played: RDR2. The Uncharted sample
  was only tested as a still image.
- **The PS5 shows a "Remote Play connected" notice** when the copy connects.
- **Remote Play limits**: one session per console; some games block scenes
  from Remote Play (the copy then shows a placeholder).
- **8 GB RAM** is tight: Windows killed idle background commands twice during
  development. Close heavy programs while playing.
- **`STATUS.md` and parts of `DECISIONS.md` are older than this report.**
  Where they disagree, this report and the code are right.

## 10. Not built yet (from the original plan)

| Item | Notes |
| --- | --- |
| `README-AR.md` | Arabic how-to for the user |
| `calibrate geometry / colour` | Not needed so far: position was right without it |
| `profile new` | Profiles are written by hand for now |
| `record / replay` | Would allow tuning on real footage without the console |
| `bench mt` blind A/B sheet | Only one engine family is left |
| `frost` and `auto` modes | Only `replace`, the hold plate, and `--no-fill` exist |
| `uvc` capture-card source | Would cut the copy delay and remove the second account |
| `color` and `detector` text models | For games with non-white subtitles |
| Translate the whole screen on demand | A "translate what is on screen now" key for letters, notes and menus; a permanent full-screen mode is not recommended (interface text everywhere, slower, more errors) |
| Better translation without delay | Idea: show the local translation at once and let a stronger model improve the cached entry in the background for the next time the line appears |

## 11. Rules for whoever changes this

- **Safety on the TV.** Only our app may be installed, started, stopped or
  have its appops changed. No root, no disabling other apps, no other
  settings. Every adb command goes through `adb.py` (allowlist) and is logged.
  `tarjim tv revert` must always undo everything.
- **Safety on the PlayStation.** Never ask for or store the PSN password.
  Never send controller input. Never change anything on the account.
- **Fail-safe first.** Nothing may leave stale Arabic on screen. Keep the
  layer TTL, the TV watchdog and the clear-on-exit.
- **Nothing in the HDMI path** unless the user decides otherwise.
- **Measure before and after.** Use `tarjim bench latency`, the session logs
  in `out/sessions/*.jsonl` (one JSON line per subtitle with every stage time)
  and the summary printed when `tarjim run` stops.
- **Run the tests** (`uv run pytest`) before committing. New behaviour gets a
  test; the synthetic frame generator is `tests/synth.py`.
- **Test dialogue is written for this project.** Do not copy lines from real
  games into tests or docs.
- **Talk to the user in simple Arabic**; keep code, comments and commits in
  English. The user is not a programmer: one concrete action at a time.
- **Licences.** This is a personal, non-distributed project. It depends on
  GPL-3.0 code (`ps5-remoteplay-mcp`) and on NLLB weights that are
  non-commercial; see `LICENSES.md` before sharing anything.

## 12. The desktop app (added 2026-11-16)

`laptop/tarjim/app/` is a desktop program on top of everything above. Start it
from the "Tarjim" shortcut on the desktop or Start menu (they run
`pythonw -m tarjim.app`, so no console window appears) or with `tarjim app`.

How it is put together:

| File | What it holds |
| --- | --- |
| `app/server.py` | A small HTTP server on `127.0.0.1:47900` (standard library only) with a JSON API, a server-sent-events stream, the native window (pywebview, i.e. Edge WebView2) and a browser app-mode fallback |
| `app/session.py` | `LiveSession` (start, watch, stop the live translation in a thread; models stay loaded between runs), `Tasks` (TV setup and test patterns in the background with their progress messages), `Hub` (event fan-out), `friendly_error` (technical failures as one plain Arabic sentence) |
| `app/shortcut.py` | Creates the desktop and Start-menu shortcuts with the icon |
| `app/web/index.html`, `app.css`, `app.js` | The interface: plain HTML, CSS and JavaScript, Arabic, right to left, no build step and no external files |

The three screens:

- **Home**: one round button (start or stop), the three devices with their
  state, what is on the TV right now, live speed / line count / frames per
  second, a quick health check with the fix for each failed item, and the
  recent lines.
- **Settings** (per game): live preview rendered by the real renderer, font,
  font size (automatic or fixed), cover the English or not, typewriter-text
  switch, how long the Arabic stays, the name glossary, and "new game".
  Every change is saved to `profiles/<game>.yaml` at once and applies the next
  time the translation is started.
- **Guide**: four steps for a first-time user: how it works, preparing the TV
  (with the address field, the setup button and the A/B test patterns),
  linking the PS5 (find it, open Sony's sign-in page, paste the redirect
  address, type the PIN), and tips.

API (all on `127.0.0.1`, refused for any other `Host` or `Origin`):
`GET /api/state`, `/api/check`, `/api/profile?name=`, `/api/preview?font=&size=&text=&fill=`,
`/api/events` (events `state`, `line`, `stats`, `task`);
`POST /api/start {profile}`, `/api/stop`, `/api/profile`, `/api/profile/new {title}`,
`/api/tv/setup {ip}`, `/api/tv/test`, `/api/ps5/discover`, `/api/ps5/open-login`,
`/api/ps5/redirect {url}`, `/api/ps5/pin {pin}`, `/api/guide-seen`, `/api/quit`.

For screenshots without a live connection, open
`http://127.0.0.1:47900/?still&demo`, `?still&view=game` or
`?still&view=guide&step=1` while the app is running.

Profile keys the app reads and writes: `title`, `glossary`, `font`,
`font_size`, `fill`, `read_scale`, `settle_ms`, `style`, `engine`.

Not in the app yet: `tv revert`, a font preview on a real game frame, editing
the detection area, and showing the session history from `out/sessions/`.

## 13. Look and region settings (added 2026-11-16)

All per game, stored in `profiles/<game>.yaml`, edited in the app's Settings
screen, turned into renderer and detector settings by `laptop/tarjim/settings.py`
(the one place the command line, the live session and the preview all use).

| Profile key | Values | Effect |
| --- | --- | --- |
| `background` | `cover` (default), `plate`, `none` | `cover`: erase the English strokes with scene colour. `plate`: erase them and put a dark box behind the Arabic. `none`: Arabic only, English stays |
| `plate_opacity` | 0.2 to 0.95 | Darkness of the plate |
| `text_color` | `#rrggbb`, or absent for automatic | Automatic takes the colour of the game's own subtitles |
| `effect` | `shadow` (default), `outline`, `none` | Soft drop shadow, dark edge all round, or nothing |
| `y_offset` | -300 to 120 px at 1080p | Move the Arabic up (negative) or down |
| `font`, `font_size` | see section 6 | |
| `region` | `{left, top, right, bottom}` as fractions 0..1 | The only part of the screen where subtitles are looked for. Default: bottom 30%, central 84% |

- Saving a profile while its session is running applies the look, the region,
  the reading time and the glossary at once (`LiveSession.apply_profile`).
- `POST /api/tv/try {name, text}` shows one sample line on the real TV for 8
  seconds with the saved look (only while no session is running, because the
  TV accepts one client).
- `GET /api/frame` returns the newest PS5 picture as a small JPEG while a
  session runs; the region editor draws its box over it.
- `GET /api/preview?name=&o=<json>&text=` renders the look over a neutral
  scene; `o` holds unsaved overrides so the preview follows the controls.
- In plate mode the stroke fill is still drawn under the plate: a translucent
  plate alone left the English readable through it.

## 14. Version 0.2: the program's own executable, new interface, phone control, names (added 2026-11-16)

Where this section disagrees with sections 12 and 13, this section is right.

### What changed for the user

| Complaint | Cause | Fix |
| --- | --- | --- |
| Pinned to the taskbar it showed "Python" | The window belonged to `pythonw.exe` | `Tarjim.exe` in the repo root hosts Python in its own process (`laptop/launcher/Tarjim.cs`, built by `launcher/build.py` with the C# compiler that ships with Windows). Verified: the window's process is `Tarjim.exe`, with its icon in the taskbar |
| A cmd / PowerShell window flashed on some buttons | `adb.exe` and PowerShell were started from a window-less process without `CREATE_NO_WINDOW` | Every child program now gets `paths.NO_WINDOW`. Verified: no console child processes |
| The interface looked cheap | Generic gradient-glass look | Redesigned: near-black "cinema room" palette with one accent (subtitle amber), a TV that plays what the real TV shows, one signal path for the three devices, a sticky live preview in the look studio |
| The screen on the TV looked like a debug page | Plain text and two default buttons | Arabic status screen: state in one sentence, the TV's address, three checks, D-pad buttons with a clear focus state. New launcher icon and banner |
| Starting it twice opened a browser copy | Second start fell back to Chrome app mode | Second start asks the running copy to come forward (`POST /api/focus`) and exits |

Other details: the title bar is painted in the app's colour (DWM), the window remembers its size and place and is kept inside the work area, closing while a session runs asks first in the app's own dialog, the health check is merged into the device path, a latency sparkline and a session clock, `tv revert` is a button in the Guide, keyboard `Ctrl+1..4` switches screens, and the new icon (the letter teh with amber dots, `launcher/make_icon.py`).

### New files

| File | What it holds |
| --- | --- |
| `Tarjim.exe` (not in git) | The program. Shortcuts on the desktop and Start menu point to it (`app/shortcut.py`) |
| `laptop/launcher/` | `Tarjim.cs`, `build.py`, `make_icon.py`, `shots.py` (headless screenshots of every screen into `out/`) |
| `laptop/tarjim/app/window.py` | The native window: title bar colour, geometry, close question, focus |
| `laptop/tarjim/app/remote.py` | Phone control: pairing, tokens, discovery, QR |
| `phone-app/` | Android phone app `dev.tarjim.phone` (Kotlin, framework only, minSdk 24) |

### Phone control

Off by default; switched on in the app's "الجوال" screen. Then the laptop also
listens on the home network, port 47901 (HTTP), and answers a UDP broadcast
`TARJIM?` on 47902 with its name.

- The phone gets the same interface as the laptop (it is responsive), minus
  what needs the laptop itself: quit, PS5 linking, TV setup/revert, managing
  phones. Enforced on the server (`LOCAL_ONLY` in `app/server.py`), not only hidden.
- Pairing: a 6-digit code shown on the laptop, single use, replaced after 6
  wrong tries with a one-minute pause. The phone then holds a random token;
  only its SHA-256 is stored in `config.json` (`phone.devices`). Requests need
  the token (header `X-Tarjim-Token`, or `?k=` for the event stream and
  images) and must be same-origin.
- The QR code on the laptop encodes `http://<laptop>:47901/?pair=<code>`: the
  phone's camera opens the interface in the browser already paired. The page
  offers the Android app (`/tarjim.apk`, served from `phone-app`'s build output).
- The Android app finds the laptop by broadcast (or a typed address), remembers
  it, and shows the laptop's page in a WebView; a built-in page handles "laptop
  not found". Extra on the phone: a "second screen" view with the current
  Arabic line in large type (screen kept on).
- **A standalone phone version (no laptop) was not built**, on purpose: it needs
  a Remote Play client, OCR and translation running on the phone, which is a
  separate project and could not be tested here. The phone is a remote and a
  second screen for the laptop.
- Windows asks once to allow `Tarjim` through the firewall when phone control
  is first switched on; without "Allow" the phone cannot connect.

### Translation: names, fixes, speed

Measured on the 395 distinct lines in `out/sessions/`:

- **Names.** "Dutch" was translated as a nationality in 10 of 10 lines, and
  other names got the model's own spelling: 14 of 59 name mentions were wrong.
  `NameGuard` (`translate.py`) tries each glossary name once in four plain
  sentences and files it as `ok`, `variant` (one consistent other spelling,
  swapped afterwards) or `proxy` (replaced in the English by a stand-in name the
  model writes reliably, "Edward", then swapped back). After: 0 of 59 wrong.
  Cost: 63 ms instead of 57 ms for lines with names; trying a game's names takes
  about 5 s the first time and is remembered (`names` table in the cache).
- **Women's names** can be marked in the glossary (profile key `female`): they
  use a female stand-in ("Victoria") so verbs come out feminine.
- Lines with names are cached per spelling, so editing a name applies at once
  (before, a cached line kept the old spelling).
- **The user's own wording.** The pencil beside a line in the feed stores a fix
  (`fix` table, `POST /api/line/fix {en, ar, profile}`); it wins over the engine
  from then on.
- Brackets the model puts around names are removed when the English has none.
- **Speed.** The engine was benchmarked alone on this laptop: 4 threads, beam 2
  gives 56 ms median; 6 threads no gain; beam 1 saves 2 ms and changes 42% of
  the outputs. So the engine is at its floor here and was left as it is. Only
  8 of 419 sentences repeat across different lines, so sentence-level caching
  would not help either. What still costs time live is sharing the CPU with the
  video decoder, and battery power.

### API added

`GET /api/hello`, `/api/phone`, `/api/phone/qr.svg`, `/tarjim.apk`;
`POST /api/pair {pin, name}`, `/api/phone {enabled}`, `/api/phone/forget {id}`,
`/api/line/fix`, `/api/focus`, `/api/tv/revert`. Events added: `phone`,
`ask-close`. `state` carries `started_at`. Glossary rows carry `f` (female).

### Verified, and not

- Verified here: 114 automated tests pass (new: names, fixes, phone access
  rules, QR read-back); `Tarjim.exe` starts, owns the window, second start
  focuses it; no console windows; the TV app update installed through
  `tv setup` and both overlay windows still answer; both Android apps build.
- **Not verified:** the phone app on a real phone (none was connected), the
  firewall prompt and a phone actually reaching the laptop, the new TV status
  screen as it looks on the TV (it was not opened, so as not to interrupt the
  TV), and a live play session with the name handling (the PS5 was off).

## 15. Installer, README and GitHub (added 2026-11-16)

- **Installer.** `dist/Tarjim-Setup-0.2.0.exe` (656 MB), built by
  `laptop/launcher/build_setup.py`. It is `launcher/Setup.cs` (a hand-drawn
  WinForms program in the app's look, compiled with the Windows C# compiler)
  with a zip archive appended; a 16-byte trailer (`TARJIMZ1` + length) marks it.
  The archive mirrors the repo layout, so the code runs unchanged: `Tarjim.exe`,
  `python/` (the relocatable CPython the venv was made from), `laptop/tarjim/`,
  `laptop/.venv/Lib/site-packages/`, the opus model, fonts, profiles, adb and
  both APKs. The installer writes `laptop/.venv/pyvenv.cfg` with the new
  location, creates the shortcuts, and registers an uninstaller under HKCU
  (the same program without its payload acts as `Uninstall.exe`).
  Per-user install to `%LOCALAPPDATA%\Programs\Tarjim`, no administrator rights.
  An update keeps the user's `profiles/` and `out/`. `/S` and `/D=<folder>` exist
  for unattended use.
- **Verified:** silent and graphical installs into a scratch folder; the
  installed `Tarjim.exe --selftest` imported every heavy library from the
  installed copy, found the model, adb and both APKs (install took 48 s);
  silent uninstall removed the folder, the registry key and the shortcuts.
  **Not verified:** installing on a second computer, and the SmartScreen
  warning an unsigned installer gets after a download.
- **README.** `README.md` (Arabic first, a short developer part in English)
  with pictures in `docs/media/`, all generated: `launcher/make_media.py` runs
  the real detector and renderer on a drawn dusk scene for `swap.gif`,
  `before.png` and `after.png`; `launcher/shots.py` takes the app screenshots
  with headless Chrome; the installer pictures are captures of the real window.
- **GitHub.** The project lives in the private repository `aketo1/tarjim`;
  release `v0.2.0` carries `Tarjim-Setup-0.2.0.exe` and the phone remote APK
  (the installer is too large for git and `dist/` is ignored).

## 16. The phone version, Xbox, and what is still open (added 2026-11-16)

- **A standalone phone version exists** in its own private repository,
  `aketo1/tarjim-phone` (report: its `docs/REPORT.md`). It does the laptop's
  whole job on an Android phone and draws on the TV through the same overlay
  app and protocol described here. It reuses this program's interface files
  (`app/web/`) with a phone mode, and the idea of `NameGuard`. It worked live
  on a Galaxy S20 FE: about 105 ms per line with the phone's screen on. Its
  translator (ML Kit) is weaker than this program's model.
  The phone *remote* in `phone-app/` here is a different thing: it only
  controls this program.
- **Xbox was asked for and is not built**, in this program or on the phone.
  Nothing in the code is Xbox-aware: `sources/` has the PS5 Remote Play
  source and the file source only. An Xbox source would be a new
  `FrameSource` behind the existing interface, and the rest of the pipeline
  would not change. Two ways to get the picture:
  1. Microsoft's home streaming ("Xbox Remote Play"): a Microsoft account
     sign-in and a WebRTC video receiver. A different protocol from Sony's;
     none of the PS5 code carries over. Needs an Xbox to develop against.
  2. An HDMI capture card with passthrough (the `uvc` source in the original
     brief): works for any console, needs the hardware, and only helps the
     laptop.
  Neither was started, and no Xbox was available to test with.
- **Things seen while reviewing that are still open** in this program:
  - The guide's TV step still assumes adb debugging is already switched on;
    a TV that refuses the connection gets one sentence, not a walkthrough.
  - The installed copy writes its logs and game profiles inside the install
    folder (`%LOCALAPPDATA%\Programs\Tarjim`), so removing the program
    removes the user's game profiles too.
  - The region editor shows the game picture only while a session runs.
  - Women's names in the glossary must be marked by hand.
  - No update check: a new version means downloading the installer again.
  - `README-AR.md` from the original brief was replaced by `README.md`.
