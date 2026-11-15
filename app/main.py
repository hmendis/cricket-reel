"""Local API + static UI. Run: uvicorn app.main:app --host 127.0.0.1 --port 8000"""
from __future__ import annotations

from contextlib import asynccontextmanager
from urllib.parse import urlparse
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, feedback, jobs, matches, media, sheet_reader, spawtz, winjob

config.ensure_user_files()


@asynccontextmanager
async def lifespan(_app):
    winjob.attach()  # every FFmpeg we start dies with the app, however the app ends
    feedback.install_ring()
    yield
    jobs.cancel_all()
    media.kill_all()


app = FastAPI(title="Cricket Reel", docs_url="/api/docs", redoc_url=None, lifespan=lifespan)
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
APP_TOKEN = os.environ.get("CRICKET_REEL_TOKEN") or None   # set per launch by the desktop app
TOKEN_COOKIE = "cr_token"


@app.middleware("http")
async def local_only(request: Request, call_next):
    """R37: answer only the app's own page. A request whose Host isn't this computer (DNS rebinding) or that comes
    from another web page (Origin / Sec-Fetch-Site) is refused. The desktop app also requires its per-launch
    token, which it gets as a same-site cookie when it loads the page."""
    host = request.headers.get("host", "")
    hostname = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
    if hostname not in ALLOWED_HOSTS:
        return JSONResponse({"error": "Not allowed."}, status_code=403)
    origin = request.headers.get("origin")
    if origin and origin != "null" and urlparse(origin).netloc != host:
        return JSONResponse({"error": "Not allowed."}, status_code=403)
    if request.headers.get("sec-fetch-site") == "cross-site":
        return JSONResponse({"error": "Not allowed."}, status_code=403)
    path = request.url.path
    if APP_TOKEN and path.startswith("/api/") and request.cookies.get(TOKEN_COOKIE) != APP_TOKEN \
            and request.headers.get("x-app-token") != APP_TOKEN:
        return JSONResponse({"error": "Not allowed."}, status_code=403)
    response = await call_next(request)
    if not path.startswith("/api/"):
        # The UI files: always check for a newer copy (ETag), so an update never mixes old and new scripts/styles.
        response.headers["Cache-Control"] = "no-cache"
    if APP_TOKEN and not path.startswith("/api/"):
        response.set_cookie(TOKEN_COOKIE, APP_TOKEN, httponly=True, samesite="strict")
    return response


@app.exception_handler(matches.MatchError)
async def _match_error(_: Request, e: matches.MatchError):
    return JSONResponse({"error": e.message}, status_code=e.status)


@app.exception_handler(sheet_reader.SheetReadError)
async def _sheet_error(_: Request, e: sheet_reader.SheetReadError):
    return JSONResponse({"error": e.message, "code": e.code}, status_code=422)


@app.exception_handler(spawtz.ImportError_)
async def _import_error(_: Request, e: spawtz.ImportError_):
    return JSONResponse({"error": e.message, "code": "import"}, status_code=422)


# ---------- Routes, one module per screen (R30) ----------
from .routes import ROUTERS  # noqa: E402 - after the app exists

for _router in ROUTERS:
    app.include_router(_router)


# ---------- Static UI ----------
app.mount("/", StaticFiles(directory=config.STATIC_DIR, html=True), name="static")
