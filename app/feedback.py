"""G4: "Provide feedback" saves a zip a later Claude session can read to fix or improve the app.

What goes in (each part can be left out): what you wrote and the screen you were on; the recent log lines;
app and environment details (versions, Quick Sync, settings); the current match's data files (never video,
audio or images). Everything passes through app.redact first: the API key, passwords, tokens and folder paths
outside the app's own folders are removed. Nothing is sent anywhere; the zip is saved in the settings folder.
"""
from __future__ import annotations

import io
import json
import logging
import platform
import sys
import time
import zipfile
from collections import deque
from pathlib import Path

from . import __version__, config, media, redact

MATCH_FILES = ("match.json", "scorecard.json", "sync.json", "work/media.json", "work/candidates.meta.json")


class RingHandler(logging.Handler):
    """Keeps the last few hundred log lines in memory (the app has no log file when run from start.bat)."""

    def __init__(self, size: int = 400):
        super().__init__(logging.INFO)
        self.lines: deque[str] = deque(maxlen=size)
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    def emit(self, record):
        try:
            self.lines.append(self.format(record))
        except Exception:  # noqa: BLE001 - logging must never break the app
            pass


RING = RingHandler()


def install_ring() -> None:
    root = logging.getLogger()
    if RING not in root.handlers:
        root.addHandler(RING)
        if root.level > logging.INFO or root.level == logging.NOTSET:
            root.setLevel(logging.INFO)


def folder() -> Path:
    return config.CONFIG_DIR / "feedback"


def environment() -> dict:
    s = dict(config.load_settings())
    try:
        ff = media.run([media.ffmpeg(), "-version"], capture=True, timeout=10).stdout.decode("utf-8", "replace").splitlines()[0]
    except Exception:  # noqa: BLE001 - FFmpeg missing is itself useful information
        ff = "not found"
    return {"app_version": __version__, "python": sys.version.split()[0], "platform": platform.platform(),
            "desktop_app": config.DESKTOP, "ffmpeg": ff, "h264_encoder": media._encoder_cache.get("h264", "not checked yet"),
            "api_key_set": bool(config.api_key()), "settings": s}


def log_text() -> str:
    parts = ["\n".join(RING.lines)]
    logs = config.CONFIG_DIR / "logs"
    for p in sorted(logs.glob("app.log*"), key=lambda p: p.stat().st_mtime)[-2:] if logs.exists() else []:
        try:
            parts.append(f"--- {p.name} (last 400 lines) ---\n" + "\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]))
        except OSError:
            pass
    return "\n".join(x for x in parts if x)


def build(message: str, screen: dict, match_id: str | None, include: dict) -> dict:
    """Write the zip; return its path and the files in it."""
    from . import matches
    stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    route = "".join(ch for ch in str(screen.get("route") or "app") if ch.isalnum() or ch in "-_")[:30] or "app"
    folder().mkdir(parents=True, exist_ok=True)
    out = folder() / f"{stamp}_{route}.zip"
    files: dict[str, str] = {
        "feedback.json": json.dumps(redact.data({"message": message, "screen": screen, "match": match_id,
                                                  "saved": stamp, "app_version": __version__}), indent=2, ensure_ascii=False),
        "README.txt": ("Feedback from Cricket Reel. feedback.json says what happened and on which screen; the other files "
                       "are the app's state at that moment. Secrets and paths outside the app folders were removed.\n"),
    }
    if include.get("env", True):
        files["environment.json"] = json.dumps(redact.data(environment()), indent=2, ensure_ascii=False)
    if include.get("logs", True):
        files["logs.txt"] = redact.text(log_text())
    if include.get("match", True) and match_id:
        try:
            d = matches.match_dir(match_id)
            for name in MATCH_FILES:
                p = d / name
                if p.exists():
                    files["match/" + name.replace("/", "_")] = redact.json_file(p)
        except matches.MatchError:
            pass
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in files.items():
            z.writestr(name, body)
    tmp = out.with_suffix(".part")
    tmp.write_bytes(buf.getvalue())
    config.replace_with_retry(tmp, out)
    return {"path": str(out), "name": out.name, "files": sorted(files)}
