"""The match library, match details and the match's videos."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .. import config, matches
from ..scorecard import validate

router = APIRouter()


@router.get("/api/matches")
def list_matches():
    return matches.list_matches()


class NewMatch(BaseModel):
    name: str = ""
    batter: str
    remember: bool = True


@router.post("/api/matches")
def create_match(body: NewMatch):
    if not body.batter.strip():
        raise HTTPException(400, "Enter your name as it's written on the score sheet.")
    if body.remember:
        config.save_settings({"batter_name": body.batter.strip()})
    return matches.create(body.name, body.batter)


def _full(match_id: str) -> dict:
    d = matches.match_dir(match_id)
    m = matches.load(match_id)
    sc = config.read_json(d / "scorecard.json")
    return {"match": m, "scorecard": sc, "validation": validate(sc) if sc else None}


@router.get("/api/matches/{match_id}")
def get_match(match_id: str):
    return _full(match_id)


class MatchPatch(BaseModel):
    name: str | None = None
    batter: str | None = None
    camera: str | None = None   # U2: camera and lens mode, saved with the match and remembered for the next one
    lens: str | None = None
    highlights: str | None = None  # 2.1: batting | bowlfield | allround - the reel picked in New match


@router.patch("/api/matches/{match_id}")
def patch_match(match_id: str, body: MatchPatch):
    with matches.lock(match_id):
        with matches.edit(match_id) as m:
            if body.batter is not None:
                m["batter"] = body.batter.strip()
            if body.highlights is not None:
                if body.highlights not in matches.REEL_TYPES:
                    raise HTTPException(400, "Highlights must be batting, bowlfield or allround.")
                m["highlights"] = body.highlights
                if not m.get("reels"):
                    m["reel_active"] = body.highlights
            if body.camera is not None or body.lens is not None:
                cam = dict(m.get("camera") or {})
                if body.camera is not None:
                    cam["model"] = body.camera.strip()[:60]
                if body.lens is not None:
                    if body.lens not in config.LENSES:
                        raise HTTPException(400, "Unknown lens mode.")
                    cam["lens"] = body.lens
                m["camera"] = cam
        if body.camera is not None or body.lens is not None:
            config.save_settings({k: v for k, v in (("camera", body.camera), ("lens", body.lens)) if v is not None})
        if body.name is not None and body.name.strip() != m["name"]:
            m = matches.rename(m, body.name)
    return _full(m["id"])


@router.delete("/api/matches/{match_id}")
def delete_match(match_id: str):
    matches.delete(match_id)
    return {"ok": True}


@router.post("/api/matches/{match_id}/videos")
async def upload_video(match_id: str, file: UploadFile = File(...)):
    d = matches.match_dir(match_id)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in matches.VIDEO_EXT:
        raise HTTPException(400, f"{file.filename}: only MP4 / MOV video files are supported.")
    dest = _reserve_video_name(match_id, d, file.filename or "video.mp4")
    size = await matches.save_upload(file, dest)
    return await _add_video(match_id, dest, file.filename, size)


def _reserve_video_name(match_id: str, d: Path, filename: str) -> Path:
    with matches.lock(match_id):  # reserve a file name no other video (or upload in progress) uses
        on_disk = {p.name.split("_", 1)[0] for p in (d / "source").iterdir()}
        dest = d / "source" / matches.next_video_name(matches.load(match_id), filename, on_disk)
        dest.with_suffix(dest.suffix + ".part").touch()
    return dest


async def _add_video(match_id: str, dest: Path, name: str, size: int) -> dict:
    info = await run_in_threadpool(matches.probe, dest)
    with matches.edit(match_id) as m:
        m["videos"].append({"file": f"source/{dest.name}", "name": name, "size": size, "probe": info})
    return m


@router.post("/api/matches/{match_id}/videos/raw")
async def upload_video_raw(match_id: str, request: Request, name: str):
    """Browser upload: the file is the request body and goes straight to the match folder (one write, no temp
    copy in %TEMP%, nothing blocking the server)."""
    d = matches.match_dir(match_id)
    if Path(name).suffix.lower() not in matches.VIDEO_EXT:
        raise HTTPException(400, f"{name}: only MP4 / MOV video files are supported.")
    dest = _reserve_video_name(match_id, d, name)
    tmp = dest.with_suffix(dest.suffix + ".part")
    size = 0
    try:
        with open(tmp, "wb") as f:
            async for chunk in request.stream():
                await run_in_threadpool(f.write, chunk)
                size += len(chunk)
        config.replace_with_retry(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    return await _add_video(match_id, dest, name, size)


class LinkIn(BaseModel):
    paths: list[str]


@router.post("/api/matches/{match_id}/videos/link")
async def link_videos(match_id: str, body: LinkIn):
    """Desktop import: use the original files where they are. Nothing is copied, so a 40 GB match is added at once.
    If a file is moved later, the match asks for it again (relink)."""
    matches.match_dir(match_id)
    added = []
    for p in body.paths:
        path = Path(p)
        if path.suffix.lower() not in matches.VIDEO_EXT or not path.is_file():
            raise HTTPException(400, f"{path.name}: not an MP4 / MOV video file that exists.")
        info = await run_in_threadpool(matches.probe, path)
        added.append({"file": str(path), "path": str(path), "linked": True, "name": path.name,
                      "size": path.stat().st_size, "probe": info})
    with matches.edit(match_id) as m:
        have = {v["file"] for v in m["videos"]}
        m["videos"] += [v for v in added if v["file"] not in have]
    return m


class RelinkIn(BaseModel):
    file: str
    path: str


@router.put("/api/matches/{match_id}/videos/relink")
def relink_video(match_id: str, body: RelinkIn):
    """A linked video was moved or renamed: point the match at its new place (same size required)."""
    new = Path(body.path)
    if not new.is_file():
        raise HTTPException(400, "That file doesn't exist.")
    with matches.edit(match_id) as m:
        v = next((v for v in m["videos"] if v["file"] == body.file), None)
        if not v or not v.get("linked"):
            raise HTTPException(404, "Video not found")
        if new.stat().st_size != v["size"]:
            raise HTTPException(400, "That file isn't the same video (its size is different).")
        v["path"] = str(new)
    return m


class Order(BaseModel):
    files: list[str]


@router.put("/api/matches/{match_id}/videos/order")
def reorder_videos(match_id: str, body: Order):
    with matches.edit(match_id) as m:
        by = {v["file"]: v for v in m["videos"]}
        if sorted(by) != sorted(body.files):
            raise HTTPException(400, "Order must list every video exactly once.")
        m["videos"] = [by[f] for f in body.files]
    return m


@router.delete("/api/matches/{match_id}/videos")
def remove_video(match_id: str, file: str):
    d = matches.match_dir(match_id)
    with matches.edit(match_id) as m:
        gone = next((v for v in m["videos"] if v["file"] == file), None)
        if gone is None:
            raise HTTPException(404, "Video not found")
        m["videos"] = [v for v in m["videos"] if v["file"] != file]
    if not gone.get("linked"):  # a linked original is yours: it's never deleted
        (d / file).unlink(missing_ok=True)
    return m
