"""Match folders: matches/<match-id>/ with match.json, scorecard.json and source/ (never modified)."""
from __future__ import annotations

import json
import logging
import re
import shutil
import threading
from contextlib import contextmanager
from datetime import date, datetime
from fractions import Fraction
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

VIDEO_EXT = {".mp4", ".mov", ".insv"}
SHEET_EXT = {".jpg", ".jpeg", ".png", ".pdf", ".webp"}


class MatchError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message, self.status = message, status


def slugify(text: str) -> str:
    s = re.sub(r"[^\w\- ]+", "", text, flags=re.UNICODE).strip()
    s = re.sub(r"\s+", "-", s)
    return s[:80] or "match"


def match_dir(match_id: str) -> Path:
    if not re.fullmatch(r"[\w\-]+", match_id):
        raise MatchError("Bad match id", 404)
    d = config.MATCHES_DIR / match_id
    if not (d / "match.json").exists():
        raise MatchError("Match not found", 404)
    return d


_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def lock(match_id: str) -> threading.RLock:
    """One lock per match. Every change to match.json happens while holding it."""
    with _locks_guard:
        return _locks.setdefault(match_id, threading.RLock())


# 2.1: the three kinds of highlight reel, and the clip kinds (roles) each one uses
REEL_TYPES = {"batting": ["batting"], "bowlfield": ["bowling", "fielding"], "allround": ["batting", "bowling", "fielding"]}
ROLES = ("batting", "bowling", "fielding", "other")
MATCH_VERSION = 2


def migrate(m: dict) -> dict:
    """Bring an older match.json up to date in memory. A 2.0 match (version 1) was batting only: it becomes a
    batting-highlights match and every clip is a batting clip from the sheet. Safe to run more than once."""
    if m.get("version", 1) < 2:
        m.setdefault("highlights", "batting")
        for c in m.get("clips") or []:
            c.setdefault("role", "batting")
            c.setdefault("source", "sheet")
            c.setdefault("phase", "batting")
        m["version"] = MATCH_VERSION
    m.setdefault("highlights", "allround")
    if m.get("reel") and not m.get("reels"):  # 2.0 had one (batting) reel; 2.1 keeps one per kind of reel
        r = dict(m.pop("reel"))
        r.setdefault("rtype", "batting")
        m["reels"] = {"batting": r}
        m.setdefault("reel_active", "batting")
    return m


def load(match_id: str) -> dict:
    """match.json (migrated to the current version), or its .bak copy if the file is damaged (power cut, disk error)."""
    return migrate(_load_raw(match_id))


def _load_raw(match_id: str) -> dict:
    d = match_dir(match_id)
    try:
        return config.read_json(d / "match.json")
    except ValueError:
        try:
            m = config.read_json(d / "match.json.bak")
        except ValueError:
            m = None
        if not m:
            raise MatchError("This match's data file is damaged and there is no good backup. Its videos and "
                             "score sheet are still in the match folder.", 500) from None
        log.warning("match.json of %s was damaged; using match.json.bak", match_id)
        return m


def save(match: dict) -> dict:
    with lock(match["id"]):
        match["updated"] = datetime.now().isoformat(timespec="seconds")
        config.write_json_atomic(config.MATCHES_DIR / match["id"] / "match.json", match, backup=True)
    return match


@contextmanager
def edit(match_id: str):
    """Load, change and save match.json under the match's lock. Nothing is written if nothing changed or
    if the block raises. Every change goes through here, so one edit can't overwrite another."""
    with lock(match_id):
        m = load(match_id)
        before = json.dumps(m, sort_keys=True)
        yield m
        if json.dumps(m, sort_keys=True) != before:
            save(m)


def _unique_id(base: str, exclude: str | None = None) -> str:
    mid, n = base, 2
    while (config.MATCHES_DIR / mid).exists() and mid != exclude:
        mid, n = f"{base}-{n}", n + 1
    return mid


def create(name: str, batter: str) -> dict:
    today = date.today().isoformat()
    name = name.strip() or f"{today} New match"
    mid = _unique_id(f"{today}_{slugify(name.replace(today, '').strip()) or 'match'}")
    d = config.MATCHES_DIR / mid
    (d / "source").mkdir(parents=True)
    (d / "work").mkdir()
    now = datetime.now().isoformat(timespec="seconds")
    return save({"version": MATCH_VERSION, "id": mid, "name": name, "auto_name": True, "created": now, "batter": batter.strip(),
                 "step": "import", "videos": [], "sheet": None, "highlights": "allround"})


def list_matches() -> list[dict]:
    out = []
    if not config.MATCHES_DIR.exists():
        return out
    for d in config.MATCHES_DIR.iterdir():
        if not (d / "match.json").exists():
            continue
        try:
            m = load(d.name)
        except (MatchError, ValueError, OSError) as e:
            # One damaged match must not hide the others.
            out.append({"id": d.name, "name": d.name, "created": "", "updated": "", "step": "damaged", "videos": 0,
                        "has_sheet": False, "summary": None, "damaged": True, "error": getattr(e, "message", str(e))})
            continue
        summary = None
        try:
            sc = config.read_json(d / "scorecard.json")
            if sc:
                from .scorecard import validate
                v = validate(sc)
                summary = {"runs": v["batter"]["calc_runs"], "balls": v["batter"]["calc_balls"],
                           "result": sc["match"].get("result", ""), "ok": v["ok"], "unsure": v["unsure"]}
        except Exception:  # noqa: BLE001 - a bad scorecard only loses the summary line
            log.warning("Couldn't read the scorecard of %s", d.name, exc_info=True)
        out.append({"id": m["id"], "name": m["name"], "created": m["created"], "updated": m.get("updated", m["created"]),
                    "step": m.get("step", "import"), "videos": len(m.get("videos", [])), "has_sheet": bool(m.get("sheet")),
                    "summary": summary, "poster": _poster(d), "clips": len(m.get("clips") or []),
                    "kinds": {r: sum(1 for c in m.get("clips") or [] if c.get("role", "batting") == r) for r in ROLES},
                    "highlights": m.get("highlights", "batting"),
                    "exports": len({f for e in m.get("exports") or [] for f in e.get("files", [])})})
    return sorted(out, key=lambda x: x["updated"], reverse=True)


def _poster(d: Path) -> int | None:
    """The second to show on the library card: your first ball, once the match is synced and has thumbnails."""
    if not (d / "work" / "thumbs").exists():
        return None
    res = config.read_json(d / "sync.json") or {}
    mine = [x["t"] for x in res.get("deliveries") or [] if x.get("facer") == "me" and x.get("t") is not None]
    return int(mine[0]) if mine else None


def rename(match: dict, new_name: str) -> dict:
    """Rename the match and its folder (folder name follows the match name)."""
    new_name = new_name.strip()
    if not new_name:
        raise MatchError("Name can't be empty")
    base = slugify(new_name.replace(" v ", "-v-"))
    m = re.match(r"(\d{4}-\d{2}-\d{2})-(.*)", base)
    if m:
        base = f"{m.group(1)}_{m.group(2)}"
    new_id = _unique_id(base, exclude=match["id"])
    if new_id != match["id"]:
        try:
            (config.MATCHES_DIR / match["id"]).rename(config.MATCHES_DIR / new_id)
        except OSError as e:
            raise MatchError(f"Couldn't rename the match folder (is a file in it open?): {e}") from e
        match["id"] = new_id
    match["name"] = new_name
    match["auto_name"] = False
    return save(match)


# R34: the workflow in order. A match's step only ever moves forward (advance), whichever screen saves.
# 2.2: the Look step is gone, but "look" stays in the order so a match saved at that step still loads (as arranged).
STEPS = ("import", "sheet", "sync", "synced", "review", "arrange", "look", "exported", "described")


def advance(m: dict, step: str) -> dict:
    """Move the match's step forward to `step` (never backwards)."""
    order = {s: i for i, s in enumerate(STEPS)}
    if order[step] > order.get(m.get("step", "import"), -1):
        m["step"] = step
    return m


def clips_by_index(m: dict) -> dict[int, dict]:
    return {c["index"]: c for c in m.get("clips") or []}


def delete(match_id: str) -> None:
    with lock(match_id):
        shutil.rmtree(match_dir(match_id))


def next_video_name(match: dict, filename: str, on_disk: set[str] | None = None) -> str:
    """'NN_name' with the first number no video of this match (or file in source/) uses, so removing a file
    never makes the next upload overwrite another one."""
    used = {v["file"].split("/")[-1].split("_", 1)[0] for v in match.get("videos") or []} | (on_disk or set())
    n = 1
    while f"{n:02d}" in used:
        n += 1
    return f"{n:02d}_{safe_filename(filename)}"


# ---------- Uploads ----------
def safe_filename(name: str) -> str:
    name = Path(name).name
    return re.sub(r"[^\w.\- ]+", "_", name) or "file"


async def save_upload(upload, dest: Path, chunk: int = 8 * 1024 * 1024) -> int:
    size = 0
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with open(tmp, "wb") as f:
            while True:
                data = await upload.read(chunk)
                if not data:
                    break
                f.write(data)
                size += len(data)
        config.replace_with_retry(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    return size


def probe(path: Path) -> dict:
    """Read duration / size / frame rate with ffprobe. Returns {'ok': False, ...} if unavailable."""
    exe = config.ffprobe_path()
    if not exe:
        return {"ok": False, "error": "FFmpeg isn't installed (winget install -e --id Gyan.FFmpeg)"}
    from . import media
    try:
        out = media.run([exe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
                        capture=True, timeout=60).stdout
        info = json.loads(out.decode("utf-8", "replace"))
    except (media.MediaError, OSError, json.JSONDecodeError) as e:
        return {"ok": False, "error": f"Couldn't read this video: {getattr(e, 'message', e)}"}
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not v:
        return {"ok": False, "error": "No video stream found"}

    def fps(s):
        try:
            f = Fraction(s)
            return float(f) if f else 0.0
        except (ValueError, ZeroDivisionError):
            return 0.0

    r_fps, avg_fps = fps(v.get("r_frame_rate", "0/1")), fps(v.get("avg_frame_rate", "0/1"))
    w, h = int(v.get("width", 0)), int(v.get("height", 0))
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(sd["rotation"])
    if abs(rot) in (90, 270):
        w, h = h, w
    return {"ok": True, "duration": float(info.get("format", {}).get("duration", 0) or 0), "width": w, "height": h,
            "fps": round(avg_fps or r_fps, 3), "vfr": bool(r_fps and avg_fps and abs(r_fps - avg_fps) > 0.01),
            "vertical": h > w, "has_audio": a is not None, "codec": v.get("codec_name", "")}
