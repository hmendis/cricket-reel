"""Sync: run it, pins, first/last shot tags, the stance reference, preview video and thumbnails."""
from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import config, fielding, jobs, matches, media, sync, sync_job

router = APIRouter()


class SyncIn(BaseModel):
    batting_start: float | None = None
    sensitivity: float | None = None   # 0..1, higher keeps more (weaker) candidate sounds


@router.post("/api/matches/{match_id}/sync")
def start_sync(match_id: str, body: SyncIn | None = None):
    d = matches.match_dir(match_id)
    m = matches.load(match_id)
    if not m["videos"]:
        raise HTTPException(400, "Add the match video first.")
    if not (d / "scorecard.json").exists():
        raise HTTPException(400, "Check and save the score sheet first.")
    start = body.batting_start if body else None
    sens = body.sensitivity if body else None
    _no_sync_running(match_id)
    job = jobs.start("sync", match_id, sync_job.STEPS, lambda j: sync_job.run(j, match_id, start, sens))
    return job.to_dict()


def _no_sync_running(match_id: str) -> None:
    """A second sync request while one is waiting or running would be dropped with its settings: say so instead."""
    j = jobs.latest_for(match_id, "sync")
    if j and j.status in jobs.ACTIVE:
        raise HTTPException(409, "A sync is already running for this match. Wait for it to finish, or cancel it "
                                 "and start again with the new settings.")


class AnchorsIn(BaseModel):
    first: float | None = None   # your first shot (s)
    last: float | None = None    # your last shot (s)


@router.put("/api/matches/{match_id}/sync/anchors")
def set_anchors(match_id: str, body: AnchorsIn):
    """S2: tag your first and last shot. The next sync places all your other balls between them."""
    with matches.edit(match_id) as m:
        m["sync_anchors"] = {k: round(v, 3) for k, v in body.model_dump().items() if v is not None and v >= 0}
    return {"anchors": m["sync_anchors"]}


class PinIn(BaseModel):
    index: int
    t: float | None = None       # None removes the pin


@router.post("/api/matches/{match_id}/sync/pin")
def pin_ball(match_id: str, body: PinIn):
    """S4: pin (or unpin) one ball and re-line-up only its over. Takes a fraction of a second."""
    sc = config.read_json(matches.match_dir(match_id) / "scorecard.json")
    dels = sync.deliveries_from_scorecard(sc) if sc else []
    if not 0 <= body.index < len(dels):
        raise HTTPException(400, "No such ball.")
    with matches.edit(match_id) as m:
        pins = dict(m.get("sync_pins") or {})
        if body.t is None:
            pins.pop(str(body.index), None)
        else:
            pins[str(body.index)] = round(float(body.t), 3)
        m["sync_pins"] = pins
    return sync_job.realign_over(match_id, dels[body.index]["over"])


class ReferenceIn(BaseModel):
    t: float | None = None       # None = automatic (1.5 s before the first-shot tag)
    off: bool = False


@router.put("/api/matches/{match_id}/sync/reference")
def set_reference(match_id: str, body: ReferenceIn):
    """S3: the frame of you at the crease that stance matching compares against."""
    with matches.edit(match_id) as m:
        m["stance_ref"] = {"t": round(body.t, 2) if body.t is not None else None, "off": body.off}
    return sync_job.overview(match_id)


@router.get("/api/matches/{match_id}/sync")
def get_sync(match_id: str):
    out = sync_job.overview(match_id)
    j = jobs.latest_for(match_id, "sync")
    out["job"] = j.to_dict() if j else None
    return out


class EvenIn(BaseModel):
    start: float
    end: float


@router.post("/api/matches/{match_id}/sync/even")
def sync_even(match_id: str, body: EvenIn):
    d = matches.match_dir(match_id)
    sc = config.read_json(d / "scorecard.json")
    if not sc or body.end <= body.start:
        raise HTTPException(400, "Pick a start and end time for the batting.")
    res = sync.spaced_evenly(sc, body.start, body.end)
    res["signature"] = sync_job.matches_signature(match_id)
    config.write_json_atomic(d / "sync.json", res)
    with matches.edit(match_id) as m:
        matches.advance(m, "synced")
    return sync_job.overview(match_id)


# ---------- 2.1: the fielding phase (split, over flags, wickets) and clips you add ----------
def _field_res(match_id: str) -> dict:
    res = config.read_json(matches.match_dir(match_id) / "sync.json")
    if not res or not res.get("fielding"):
        raise HTTPException(400, "Run the sync first. The fielding phase needs the other team's innings from the score sheet.")
    return res["fielding"]


def _field_edit(match_id: str, fn) -> dict:
    """Change match.json "fielding" with fn(f), re-place the fielding phase (cached, fast) and return the overview."""
    _field_res(match_id)
    with matches.edit(match_id) as m:
        f = dict(m.get("fielding") or {})
        fn(f)
        m["fielding"] = f
    sync_job.refresh_fielding(match_id)
    return sync_job.overview(match_id)


class BoundIn(BaseModel):
    t: float | None = None       # None = back to the guess


@router.put("/api/matches/{match_id}/fielding/bound")
def set_bound(match_id: str, body: BoundIn):
    """Where fielding ends and batting starts (or the reverse). Unflagged overs are re-spread. The batting balls
    keep their times until the next full re-sync."""
    def fn(f):
        if body.t is None:
            f.pop("bound", None)
        else:
            f["bound"] = round(max(0.0, body.t), 1)
    return _field_edit(match_id, fn)


class HasBattingIn(BaseModel):
    on: bool


@router.put("/api/matches/{match_id}/fielding/has-batting")
def set_has_batting(match_id: str, body: HasBattingIn):
    """A Bowling + Fielding reel treats the whole recording as fielding. 'This video has our batting too' turns the
    phase split back on."""
    def fn(f):
        f["has_batting"] = body.on
    return _field_edit(match_id, fn)


class FlagIn(BaseModel):
    over: int
    t: float | None = None       # None removes the flag


@router.put("/api/matches/{match_id}/fielding/flag")
def set_flag(match_id: str, body: FlagIn):
    """The first ball of over N is at t (F key). Overs between flags are spread evenly."""
    if not 1 <= body.over <= fielding.N_OVERS:
        raise HTTPException(400, "No such over.")

    def fn(f):
        flags = dict(f.get("flags") or {})
        if body.t is None:
            flags.pop(str(body.over), None)
        else:
            flags[str(body.over)] = round(max(0.0, body.t), 2)
        f["flags"] = flags
    return _field_edit(match_id, fn)


class WicketIn(BaseModel):
    id: str                      # "12.1"
    t: float | None = None       # None un-confirms it


@router.put("/api/matches/{match_id}/fielding/wicket")
def confirm_wicket(match_id: str, body: WicketIn):
    """Confirm a wicket at t (Enter in the Check wickets queue, or dropping its marker on the timeline). If that's
    more than 5 s from its guess, the unconfirmed wickets of that over and the next one move with it."""
    w = next((x for x in _field_res(match_id)["wickets"] if x["id"] == body.id), None)
    if not w:
        raise HTTPException(400, "No such wicket.")

    def fn(f):
        conf = dict(f.get("confirmed") or {})
        if body.t is None:
            conf.pop(body.id, None)
        else:
            conf[body.id] = round(max(0.0, body.t), 2)
            f["shift"] = fielding.respread(f.get("shift") or {}, w, body.t)
        f["confirmed"] = conf
    return _field_edit(match_id, fn)


@router.get("/api/matches/{match_id}/fielding/noise")
def noise(match_id: str, t0: float, t1: float):
    """Voice energy over its baseline (dB, one value per 0.1 s) and claps between t0 and t1, for the queue's strip."""
    from .. import celebrate
    d = matches.match_dir(match_id)
    state = config.read_json(d / "work" / "media.json", {}) or {}
    if not state.get("signature") or not (d / "work" / "celebrate.npz").exists():
        raise HTTPException(404, "No celebration data yet - run the sync first.")
    F = celebrate.load_or_compute(d / "work", state["signature"], state.get("motion_fps", 10))
    b = F["bin"]
    lo, hi = max(0, int(t0 / b)), min(len(F["voice_db"]), int(t1 / b) + 1)
    if hi - lo > 1200:
        raise HTTPException(400, "Ask for two minutes at most.")
    ex = F["voice_db"][lo:hi] - F["base_db"][lo:hi]
    return {"t0": lo * b, "bin": b, "db": [round(float(x), 1) for x in ex], "claps": [round(lo * b + i * b, 1) for i, c in enumerate(F["claps"][lo:hi]) if c],
            "threshold": celebrate.MIN_DB}


class ManualIn(BaseModel):
    t: float
    role: str = "other"
    label: str = ""


@router.post("/api/matches/{match_id}/manual-clips")
def add_manual(match_id: str, body: ManualIn):
    """Add a clip at t in any phase (A key). Re-sync never moves it."""
    if body.role not in matches.ROLES:
        raise HTTPException(400, "Kind must be batting, bowling, fielding or other.")
    with matches.edit(match_id) as m:
        clips = list(m.get("manual_clips") or [])
        n = max([int(c["id"][1:]) for c in clips] + [0]) + 1
        clips.append({"id": f"m{n}", "t": round(max(0.0, body.t), 2), "role": body.role, "label": body.label.strip()[:40]})
        m["manual_clips"] = sorted(clips, key=lambda c: c["t"])
    return sync_job.overview(match_id)


class ManualMoveIn(BaseModel):
    t: float


@router.put("/api/matches/{match_id}/manual-clips/{clip_id}")
def move_manual(match_id: str, clip_id: str, body: ManualMoveIn):
    with matches.edit(match_id) as m:
        c = next((c for c in m.get("manual_clips") or [] if c["id"] == clip_id), None)
        if not c:
            raise HTTPException(404, "No such clip.")
        c["t"] = round(max(0.0, body.t), 2)
        m["manual_clips"] = sorted(m["manual_clips"], key=lambda c: c["t"])
    return sync_job.overview(match_id)


@router.delete("/api/matches/{match_id}/manual-clips/{clip_id}")
def delete_manual(match_id: str, clip_id: str):
    with matches.edit(match_id) as m:
        m["manual_clips"] = [c for c in m.get("manual_clips") or [] if c["id"] != clip_id]
    return sync_job.overview(match_id)


@router.get("/api/matches/{match_id}/waveform")
def waveform(match_id: str):
    """R16: the waveform as raw bytes (one 0-255 peak per 50 ms), cacheable; the step is in X-Step."""
    d = matches.match_dir(match_id) / "work"
    p = d / "waveform.bin"
    if not p.exists():
        wf = config.read_json(d / "waveform.json")
        if not wf:
            raise HTTPException(404, "No waveform yet - run the sync first.")
        p.write_bytes(bytes(min(255, round(v * 255)) for v in wf["peaks"]))
    step = (config.read_json(d / "waveform.json", {}) or {}).get("step", 0.05)
    return FileResponse(p, media_type="application/octet-stream", headers={"X-Step": str(step), "Cache-Control": "max-age=3600"})


@router.get("/api/matches/{match_id}/proxy")
def proxy(match_id: str):
    p = matches.match_dir(match_id) / "work" / "proxy.mp4"
    if not p.exists():
        raise HTTPException(404, "No preview video yet — run the sync first.")
    return FileResponse(p, media_type="video/mp4")


@router.get("/api/matches/{match_id}/thumb/{sec}")
def thumb(match_id: str, sec: int):
    """One thumbnail (second `sec`), cut from its sprite sheet (or the old one-file-per-second layout)."""
    from fastapi.responses import Response
    d = matches.match_dir(match_id) / "work" / "thumbs"
    sec = max(0, sec)
    sprite = d / f"sprite_{sec // 100:03d}.jpg"
    if sprite.exists():
        return Response(_thumb_from_sprite(str(sprite), sprite.stat().st_mtime_ns, sec % 100), media_type="image/jpeg",
                        headers={"Cache-Control": "max-age=3600"})
    p = d / f"{sec + 1:05d}.jpg"
    if not p.exists():
        raise HTTPException(404, "No thumbnail")
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})


@router.get("/api/matches/{match_id}/sprite/{n}")
def sprite(match_id: str, n: int):
    """Sprite sheet n: seconds 100n..100n+99 as a 10x10 grid of 90x160 thumbnails (R13)."""
    p = matches.match_dir(match_id) / "work" / "thumbs" / f"sprite_{max(0, n):03d}.jpg"
    if not p.exists():
        raise HTTPException(404, "No thumbnails")
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})


@lru_cache(maxsize=512)
def _thumb_from_sprite(path: str, _mtime: int, k: int) -> bytes:
    import io
    from PIL import Image
    w, h, cols = media.SPRITE["w"], media.SPRITE["h"], media.SPRITE["cols"]
    with Image.open(path) as im:
        tile = im.crop(((k % cols) * w, (k // cols) * h, (k % cols + 1) * w, (k // cols + 1) * h)).convert("RGB")
    buf = io.BytesIO()
    tile.save(buf, "JPEG", quality=80)
    return buf.getvalue()
