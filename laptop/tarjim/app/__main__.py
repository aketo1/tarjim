import sys


def _selftest(path: str) -> int:
    """`Tarjim.exe --selftest <file>`: prove that the executable hosts Python, the project's
    packages and the window toolkit, without opening anything."""
    import json
    import os

    facts = {"executable": sys.executable, "prefix": sys.prefix, "host": os.environ.get("TARJIM_HOST")}
    try:
        import clr  # noqa: F401  (pythonnet: what the window is built on)
        import webview

        import tarjim
        from tarjim import paths

        heavy = []
        for name in ("cv2", "numpy", "ctranslate2", "sentencepiece", "onnxruntime", "rapidocr", "uharfbuzz",
                     "freetype", "yaml", "segno", "psutil", "PIL", "ps5_remoteplay_mcp.vendor.pyremoteplay",
                     "tarjim.sources.xbox"):
            __import__(name)
            heavy.append(name)
        model = paths.REPO / "models" / "opus-mt-tc-big-en-ar-ct2" / "model.bin"
        facts.update(ok=True, tarjim=tarjim.__file__, webview=webview.__file__, repo=str(paths.REPO),
                     imported=heavy, model=model.exists(), adb=str(paths.adb_path()), tv_apk=paths.APK.exists(),
                     phone_apk=paths.PHONE_APK.exists(), fonts=(paths.REPO / "fonts" / "Harmattan-Regular.ttf").exists())
    except Exception as exc:  # reported to the caller through the file
        facts.update(ok=False, error=repr(exc))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(facts, fh, indent=1)
    return 0 if facts["ok"] else 1


if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
    sys.exit(_selftest(sys.argv[2]))

from .server import main  # noqa: E402

sys.exit(main())
