"""Describe (E2), the Claude cost summary (E3) and the quick links (E4)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import config, describe, jobs, matches, usage

router = APIRouter()


@router.get("/api/matches/{match_id}/describe")
def get_describe(match_id: str):
    return describe.overview(match_id)


class FileIn(BaseModel):
    name: str
    kind: str = "clip"
    index: int | None = None
    rtype: str | None = None    # 2.1: which reel (batting / bowlfield / allround)
    prompt: str = Field("", max_length=1000)


class DescribeIn(BaseModel):
    files: list[FileIn]


@router.post("/api/matches/{match_id}/describe")
def start_describe(match_id: str, body: DescribeIn):
    """Write the descriptions for the given exported files (one Claude call each), as a job."""
    key = config.api_key()
    if not key:
        raise HTTPException(400, "The Claude API key is missing. Paste it in Settings, then try again.")
    d = matches.match_dir(match_id)
    files = [f.model_dump() for f in body.files if (d / "exports" / f.name).exists()]
    if not files:
        raise HTTPException(400, "Export the reel or a clip first.")
    model = config.load_settings()["model"]

    def run(job):
        try:
            return describe.run(job, match_id, files, model, key)
        except describe.DescribeError as e:
            raise RuntimeError(e.message) from e

    job = jobs.start("describe", match_id, ["Write the descriptions"], run)
    return job.to_dict()


@router.get("/api/usage")
def get_usage(match_id: str | None = None):
    """E3: Claude API cost for a match (by step) and since the app started."""
    m = matches.load(match_id) if match_id else None
    return usage.summary(m)
