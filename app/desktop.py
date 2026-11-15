"""Desktop launcher: the app in its own window (Edge WebView2 via pywebview), no browser tab, no console.

- One copy only: a second launch brings the running window to the front and exits.
- Shows a splash while the local server starts on a free 127.0.0.1 port.
- Closing the window cancels running jobs (killing FFmpeg), stops the server and exits - no leftovers.
"""
from __future__ import annotations

import ctypes
import os
import socket
import sys
import threading
import time
import urllib.request

os.environ.setdefault("CRICKET_REEL_DESKTOP", "1")

TITLE = "Cricket Reel"
MUTEX_NAME = "Local\\CricketReel.SingleInstance"

# The start-up screen, in the design v2 colours (no logo: the plain app name and the version).
SPLASH = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;height:100%;background:#07080B;color:#F2F4F8;font-family:'Segoe UI',sans-serif;display:grid;place-items:center;overflow:hidden}
body::before{content:"";position:fixed;inset:0;background:radial-gradient(50% 40% at 50% 45%,rgba(74,222,128,.14),transparent 70%)}
.box{position:relative;text-align:center} h1{font:700 40px 'Segoe UI';letter-spacing:-.03em;margin:0}
p{color:#8A90A0;margin:0;font-size:13px} p.v{font:500 13px Consolas,monospace;margin:6px 0 0}
.bar{width:220px;height:4px;background:#222632;border-radius:4px;overflow:hidden;margin:28px auto 12px}
.bar i{display:block;height:100%;width:40%;background:#4ADE80;border-radius:4px;box-shadow:0 0 12px #4ADE80;animation:s 1.1s ease-in-out infinite}
@keyframes s{0%{margin-left:-40%}100%{margin-left:100%}}</style></head><body><div class="box">
<h1>Cricket Reel</h1><p class="v">Version __VERSION__</p><div class="bar"><i></i></div><p>Starting…</p></div></body></html>"""


def _single_instance() -> object | None:
    """Return a mutex handle if we're the first copy; otherwise focus the existing window and return None."""
    if os.name != "nt":
        return object()
    k32 = ctypes.windll.kernel32
    h = k32.CreateMutexW(None, False, MUTEX_NAME)
    if k32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        u32 = ctypes.windll.user32
        hwnd = u32.FindWindowW(None, TITLE)
        if hwnd:
            u32.ShowWindow(hwnd, 9)  # SW_RESTORE
            u32.SetForegroundWindow(hwnd)
        return None
    return h


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Api:
    """Functions the page can call as window.pywebview.api.* (desktop only)."""

    # Attributes starting with "_" aren't exposed to the page (pywebview would otherwise walk into the native
    # window object and recurse forever).
    def __init__(self):
        self._window = None

    def pick_folder(self):
        import webview
        res = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        return res[0] if res else None

    def pick_videos(self):
        """Native file picker for match videos: returns their paths, so the app can use them in place (R3)."""
        import webview
        res = self._window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=True,
                                              file_types=("Video files (*.mp4;*.mov;*.MP4;*.MOV)", "All files (*.*)"))
        return list(res) if res else []


class RotatingLog:
    """A file-like log for stdout/stderr: app.log, rotated at 1 MB, three files kept (R39). Secrets are removed
    as lines are written (paths stay in the local log; the feedback bundle removes those too)."""

    def __init__(self, path, max_bytes: int = 1_000_000, keep: int = 3):
        self.path, self.max_bytes, self.keep = path, max_bytes, keep
        self.lock = threading.Lock()
        self.f = open(path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - lives for the whole run

    def write(self, s: str) -> int:
        from app import redact
        with self.lock:
            if self.f.tell() > self.max_bytes:
                self._rotate()
            self.f.write(redact.text(s) if ("sk-" in s or "=" in s or "Bearer" in s) else s)
        return len(s)

    def _rotate(self):
        self.f.close()
        for i in range(self.keep - 1, 0, -1):  # app.log.1 -> app.log.2, app.log -> app.log.1
            src = self.path if i == 1 else self.path.with_name(f"{self.path.name}.{i - 1}")
            if src.exists():
                os.replace(src, self.path.with_name(f"{self.path.name}.{i}"))
        self.f = open(self.path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115

    def flush(self):
        self.f.flush()

    def isatty(self):
        return False


def _log_to_file():
    """A windowed app has no console: sys.stdout/stderr are None, which breaks logging. Send them to a log file."""
    from app import config
    logs = config.CONFIG_DIR / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    f = RotatingLog(logs / "app.log")
    f.write(f"\n--- start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    if sys.stdout is None:
        sys.stdout = f
    if sys.stderr is None:
        sys.stderr = f
    return f


def main() -> int:
    if _single_instance() is None:
        return 0
    _log_to_file()
    import uvicorn
    import webview

    import secrets
    # R37: a fresh random token per launch, read by app.main; the page gets it as a same-site cookie, other pages can't.
    os.environ["CRICKET_REEL_TOKEN"] = secrets.token_urlsafe(24)
    from app import config, jobs, media, winjob
    from app.main import app as fastapi_app

    winjob.attach()  # FFmpeg dies with the app even if it's ended from Task Manager

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(fastapi_app, host="127.0.0.1", port=port, log_level="warning",
                                           access_log=False, log_config=None))
    def serve():
        print(f"server starting on 127.0.0.1:{port}", flush=True)
        try:
            server.run()
        except Exception:  # noqa: BLE001 - make startup failures visible in the log
            import traceback
            traceback.print_exc()

    t = threading.Thread(target=serve, daemon=True, name="server")
    t.start()

    api = Api()
    from app import __version__
    splash = SPLASH.replace("__VERSION__", __version__)
    window = webview.create_window(TITLE, html=splash, width=1440, height=900, min_size=(1280, 720),
                                   background_color="#07080B", js_api=api)
    api._window = window

    def load_when_ready():
        url = f"http://127.0.0.1:{port}/"
        for _ in range(300):  # up to ~30 s on a cold start
            try:
                # The page itself, not /api/…: the API needs the window's token cookie, which only the page sets.
                urllib.request.urlopen(url, timeout=1).read()
                window.load_url(url)
                return
            except Exception:  # noqa: BLE001 - server not up yet
                time.sleep(0.1)
        window.load_html(splash.replace("Starting…", "The app couldn't start. Close this window and try again."))

    def on_closing():
        jobs.cancel_all()  # kills FFmpeg so nothing is left running
        media.kill_all()
        server.should_exit = True

    window.events.closing += on_closing
    storage = config.CONFIG_DIR / "webview"
    webview.start(load_when_ready, private_mode=False, storage_path=str(storage))
    server.should_exit = True
    t.join(timeout=5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
