"""Arrange: the reel, music and the preview render."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError

from .. import config, jobs, matches, reel, render

router = APIRouter()


@router.get("/api/matches/{match_id}/arrange")
def get_arrange(match_id: str, rtype: str | None = None):
    return reel.load(match_id, rtype)


class ReelTypeIn(BaseModel):
    rtype: str


@router.post("/api/matches/{match_id}/reels")
def add_reel(match_id: str, body: ReelTypeIn):
    """Make another kind of reel (Batting, Bowling + Fielding or All-round) from the same clips."""
    if body.rtype not in reel.RTYPE_NAMES:
        raise HTTPException(400, "A reel is Batting, Bowling + Fielding or All-round.")
    return reel.load(match_id, body.rtype)


@router.delete("/api/matches/{match_id}/reels/{rtype}")
def delete_reel(match_id: str, rtype: str):
    return reel.remove(match_id, rtype)


class ReelIn(BaseModel):
    reel: dict


@router.put("/api/matches/{match_id}/reel")
def put_reel(match_id: str, body: ReelIn):
    try:
        return reel.save(match_id, body.reel)
    except ValidationError as e:
        raise HTTPException(400, f"Reel settings are invalid: {e.errors()[0]['msg']}") from e


@router.post("/api/matches/{match_id}/reel/auto")
def auto_reel(match_id: str, rtype: str | None = None):
    return reel.auto(match_id, rtype)


@router.post("/api/matches/{match_id}/music")
async def upload_music(match_id: str, file: UploadFile = File(...)):
    d = matches.match_dir(match_id)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac"):
        raise HTTPException(400, "Music must be an MP3, M4A, AAC, WAV, OGG or FLAC file.")
    incoming = d / "source" / f"incoming_music{ext}"
    await matches.save_upload(file, incoming)  # the old music is only removed once the new file is saved
    dest = d / "source" / f"music{ext}"
    with matches.edit(match_id) as m:
        for old in (d / "source").glob("music.*"):
            old.unlink()
        config.replace_with_retry(incoming, dest)
        r = reel.of(m)
        r["music"] = dest.name
        m["reels"] = {**(m.get("reels") or {}), r["rtype"]: r}
        m["music_name"] = file.filename
    return {"music": dest.name, "name": file.filename}


@router.delete("/api/matches/{match_id}/music")
def delete_music(match_id: str):
    d = matches.match_dir(match_id)
    with matches.edit(match_id) as m:
        for r in (m.get("reels") or {}).values():
            r["music"] = None
        m.pop("music_name", None)
        for old in (d / "source").glob("music.*"):
            old.unlink()
    return {"ok": True}


@router.post("/api/matches/{match_id}/render-preview")
def render_preview(match_id: str):
    d = matches.match_dir(match_id)
    m = matches.load(match_id)
    r = reel.of(m)
    clips = matches.clips_by_index(m)

    def run(job):
        job.update(step=0, detail=f"{len(r['entries'])} clips")
        return render.render_preview(d, r, clips, lambda f: job.update(progress=f), job.cancel)

    job = jobs.start("render", match_id, ["Render the reel preview (540×960)"], run)
    return job.to_dict()


@router.get("/api/matches/{match_id}/reel-preview")
def reel_preview(match_id: str):
    p = matches.match_dir(match_id) / "work" / "reel_preview.mp4"
    if not p.exists():
        raise HTTPException(404, "No rendered preview yet")
    return FileResponse(p, media_type="video/mp4", headers={"Cache-Control": "no-store"})
