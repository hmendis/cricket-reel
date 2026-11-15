"""Background jobs and their progress stream."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from .. import jobs

router = APIRouter()


@router.get("/api/jobs")
def list_jobs():
    return [j.to_dict() for j in jobs.running()]


@router.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    j = jobs.get(job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    return j.to_dict()


@router.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    j = jobs.get(job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    jobs.cancel(j)
    return j.to_dict()


@router.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request):
    """Server-sent events: one JSON progress message every 0.5 s until the job ends."""
    import asyncio
    import json as _json
    from fastapi.responses import StreamingResponse

    j = jobs.get(job_id)
    if not j:
        raise HTTPException(404, "Job not found")

    async def stream():
        while True:
            if await request.is_disconnected():
                return
            data = j.to_dict()
            yield f"data: {_json.dumps(data)}\n\n"
            if data["status"] not in jobs.ACTIVE:
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})
