"""Review: the clips."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError

from .. import config, jobs, matches, review, sync_job
from .sync import _no_sync_running

router = APIRouter()


@router.get("/api/matches/{match_id}/review")
def get_review(match_id: str):
    return review.load(match_id)


class ClipsIn(BaseModel):
    clips: list[dict]


@router.put("/api/matches/{match_id}/clips")
def put_clips(match_id: str, body: ClipsIn):
    try:
        return {"clips": review.save(match_id, body.clips)}
    except ValidationError as e:
        raise HTTPException(400, f"Clip data is invalid: {e.errors()[0]['msg']}") from e


@router.post("/api/matches/{match_id}/resync-fixes")
def resync_with_fixes(match_id: str):
    """Pin every clip I moved or confirmed, then re-run the sync around those pins."""
    _no_sync_running(match_id)
    pins = review.pins_from_fixes(match_id)
    sync_res = config.read_json(matches.match_dir(match_id) / "sync.json") or {}
    start = sync_res.get("batting_start")
    job = jobs.start("sync", match_id, sync_job.STEPS, lambda j: sync_job.run(j, match_id, start))  # same sensitivity
    return {"job": job.to_dict(), "pins": pins}
