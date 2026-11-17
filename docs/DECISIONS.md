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

## Gate 1 and TV findings (2026-11-15)

- **TCL blocks third-party background starts.** logcat showed
  `TclAppBoot ... isAllow='false' reason='callee_does't_have_OP_AUTO_START_permission'`
  for our accessibility bind and `block startForeground for dev.tarjim.tv`,
  after which the system killed the process (`startForegroundService() did
  not then call startForeground()`). `appops get dev.tarjim.tv` listed the
  TCL appop `APP_AUTO_START: ignore`. Setup now sets it to `allow` for our
  package only (our app's appops are inside the safety rules) and revert
  sets it back to `default`.
- **Accessibility bind is not retried by the system** after that refusal;
  setup takes only our own entry out of `enabled_accessibility_services` and
  puts it back, leaving the user's other entry
  (`com.mmda.najd/...RemoteAccess`) untouched.
- **Default window: A** (`TYPE_APPLICATION_OVERLAY`). T1: both A and B are
  visible over HDMI; A needs no accessibility service.
- **T2 outcome**: user played Red Dead Redemption 2 on their own account while
  the copy ran on the account `Red_deed2018`: controller, sound and picture
  unaffected; video output stayed 3840x2160 60 Hz YUV422 HDR, HDCP 2.3 before
  and during (photos in `samples/tv-photos/`). The only pop-up is the PS5's
  "Remote Play connected" notice. The 15-minute measured run was stopped
  early at the user's request, so the 30-minute fps/reconnect criterion is
  still unmeasured; the 20-second run gave 30.1 fps at 1080p, 0 reconnects.
- **The TV shows HDR, the copy is SDR.** Fill colours come from the SDR copy
  and will not match the HDR picture exactly; expected to show in T4.

## M3 (2026-11-15)

- **Arabic shaping: HarfBuzz (`uharfbuzz` 0.57) + FreeType**, with our own
  small bidi (RTL base, LTR runs for Latin and numbers) because Pillow here
  has no RAQM. Golden images inspected by eye: joined letters, lam-alef,
  tanween, digits, mixed Latin, end punctuation.
- **Renderer matches the brief's reference** on the Uncharted sample:
  ascender 26 px, baselines 918/971, Harmattan at 47 px.
- **OCR: RapidOCR 3.10 (PP-OCR English recognition, onnxruntime), recognition
  only** on our own line crops scaled to 48 px height. Both user samples read
  exactly; synthetic CER <= 2% (test). 77 ms p50 per block. Windows.Media.Ocr
  and Tesseract were not evaluated: RapidOCR already meets accuracy and the
  120 ms budget.
- **Default local translator: `opus-big`** (Helsinki-NLP/opus-mt-tc-big-en-ar,
  CC-BY-4.0). Measured on this laptop over 22 test lines: p50 148 ms, p90
  278 ms, versus NLLB-200-distilled-600M int8 at p50 635 ms, p90 916 ms
  (misses the 250 ms budget). Opus output also read better on the test lines
  ("retreat" -> الخلوة vs الانسحاب; "raft" -> طوف vs القارب).
- **Models are third-party CTranslate2 conversions downloaded ready-made**
  (`ai-path/opus-mt-tc-big-en-ar-ct2`, `JustFrederik/nllb-200-distilled-600M-ct2-int8`,
  tokenizers from the official Helsinki-NLP repo) instead of running
  `ct2-transformers-converter` locally: converting needs PyTorch and several
  GB of RAM on an 8 GB machine. A CT2 `model.bin` is data, not code; the risk
  is translation quality only.
- **Both models dropped every sentence after the first** ("Did you hear
  that? Something moved." -> only the question). Lines are now split into
  sentences, translated as a batch and rejoined; dropped end punctuation is
  restored from the English.
- **Speed work**: `cv2.min` instead of numpy's channel min (23 ms -> 2.7 ms)
  and a square top-hat kernel (6 ms -> 0.9 ms) brought detection from 41 ms to
  about 12 ms; background estimation runs at half resolution (32 ms -> 14 ms).
- **OCR, translation and rendering run inline** in the frame loop for now
  (about 0.3 s per new line during which tracking pauses). Simple and
  deterministic; moving them to a worker is an M5 option.

## Live speed work (2026-11-15)

- **Gemini is not the live default.** Tuned (`store=False`, thinking minimal,
  one attempt) it measured p50 848 ms per line in a quiet benchmark, 76 input
  + 16 output tokens. Live during play it was p50 1213 ms and 13 of 24 lines
  hit the 1.2 s timeout and were then translated locally on top. The free
  tier also returned 429 after about 28 requests in two minutes. The engine
  stays available (`--engine gemini`).
- **The laptop was on battery** during the slow runs (local MT 405 ms p50).
  On mains, with the process set to high priority and Windows power
  throttling switched off for it, MT under the real stream load is 85 ms p50
  on the worker thread and detection 3 ms.
- **Reading starts at first sight** (worker thread) instead of after the
  settle time. 15-minute live run in Red Dead Redemption 2 on mains, local
  engine: 56 lines shown, all acked as drawn by the TV; first sight to Arabic
  on the TV p50 176 ms, p90 262 ms (was about 700 ms: 150 ms settle + 546 ms).
  Stream 30 fps, 0 reconnects. 45 candidate blocks were rejected as
  non-subtitles.
- **OpenCV thread count does not matter** for this load (1, 2 or 12 threads:
  MT 85-90 ms, detect 3-4 ms), so it is left at the default.
- **Own executable by hosting Python, not by wrapping it** (2026-11-16). A shortcut to
  `pythonw.exe` makes Windows show "Python" when the program is pinned. `Tarjim.exe` is a
  40-line C# program (compiled with the `csc.exe` that ships with Windows) that loads
  `python312.dll` and calls `Py_Main` with `-m tarjim.app`, setting `__PYVENV_LAUNCHER__`
  so the project's environment is used. Checked: the window's process is `Tarjim.exe` and
  pywebview (pythonnet) works inside it.
- **Glossary names through stand-ins** (2026-11-16). On 395 logged lines the model got 14 of
  59 name mentions wrong ("Dutch" as a nationality 10 of 10). Replacing an unreliable name
  by "Edward" before translating and swapping back gave 0 wrong, at 63 ms vs 57 ms.
  Stand-ins were chosen by checking that the model writes them identically in seven
  different sentences (Edward, Harold, Leonard, Jonathan; Victoria, Catherine for women).
- **Translation engine settings unchanged** (2026-11-16). Alone on this laptop: 2 threads
  76 ms, 4 threads 56 ms, 6 threads 56 ms; beam 1 54 ms but 34 of 80 outputs differ;
  `int8_float32` 58 ms. Nothing to gain.
- **Phone = remote control, not a second brain** (2026-11-16). A phone-only version needs a
  Remote Play client, OCR and translation on the phone; not attempted. The phone shows the
  laptop's own interface over the home network after pairing with a one-time code.

## Translation rules and speed (2026-11-18)

- **8 model threads, not 4.** While the laptop decoded a 1080p 30 fps H.264 picture in real
  time and searched every frame (as in play): 4 threads 102 / 105 ms per sentence, 6 threads
  92 / 118 ms, 8 threads 87 / 114 ms; the picture stayed at 30 fps each time. The earlier
  "4x slower" with more threads is not seen any more; 8 is kept, 4 is the fallback.
- **Female stand-in: Catherine, not Victoria.** On 8 longer lines with women's names,
  "Victoria" broke 4 (a masdar for the command: «الذهاب الحصول على بعض النوم»), "Sarah" 2,
  "Mary" 1, "Catherine" and "Anna" none. "Anna" was not chosen: «آنا» is one hamza from
  «أنا» ("I").
- **Groups get a plural stand-in** ("soldiers"): one man's name made a group's verbs singular
  («البينكرتون سيلحق»).
- **Gender as one table for whole verb families**, not a rule per sentence: the earlier
  rules fixed the exact lines they were written for; a list of 193 masculine commands, with
  the feminine derived (plus 30 irregular pairs) and object endings, covers every line.
  Commands change only where a command can stand (start, after punctuation, «و/ف» joined,
  after «ثم», after «لا»), so «جدي» (my grandfather), «دوري» (my turn), «وقف الرجل» (stood) and
  «أذهب» ("I go") stay as they are.
- **A rule is judged on sentences written after it.** Antigravity scored 100/100 on its own
  set but improved 2 of 22 new sentences; after the fixes, a set written last: 4 better,
  1 worse, 15 the same.
