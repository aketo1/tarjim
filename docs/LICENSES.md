# Licences

Personal, non-distributed project. Listed for the day it is ever shared.

| Component | Use | Licence |
| --- | --- | --- |
| Python 3.12 | runtime | PSF-2.0 |
| uv | Python/venv manager | Apache-2.0 OR MIT |
| NumPy | arrays | BSD-3-Clause |
| Pillow | images, test patterns | MIT-CMU (HPND) |
| pytest | tests (dev only) | MIT |
| ps5-remoteplay-mcp 0.2.2 (vendored pyremoteplay 0.7.6) | receive-only Remote Play session | GPL-3.0-only |
| PyAV (bundles FFmpeg) | H.264 decoding, video files | BSD-3-Clause (FFmpeg: LGPL/GPL builds) |
| aiohttp, requests, cryptography, pycryptodomex, protobuf, psutil, pyee | needed by pyremoteplay | Apache-2.0 / BSD / MIT family |
| mcp, pywebview, pythonnet, pysdl2, httpx | installed as dependencies of ps5-remoteplay-mcp, never imported | MIT / BSD-3-Clause / zlib family |
| hatchling | build backend (dev only) | MIT |
| Android platform-tools (adb) | TV setup | Android SDK licence (proprietary terms; adb source Apache-2.0) |
| Android SDK platform / build-tools | building the TV app | Android SDK licence (must be accepted by the user) |
| Android Gradle Plugin, Gradle | building the TV app | Apache-2.0 |
| Eclipse Temurin JDK 17 | building the TV app | GPL-2.0 with Classpath Exception |
| Kotlin (bundled with AGP) | TV app language | Apache-2.0 |

Not used yet; candidates for later milestones and their licences:
`chiaki-ng` AGPL-3.0, RapidOCR Apache-2.0,
CTranslate2 MIT, NLLB-200 weights CC-BY-NC-4.0, OPUS-MT weights CC-BY-4.0,
Arabic fonts (Harmattan, Noto, IBM Plex Sans Arabic) OFL-1.1.
