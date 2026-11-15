"""Export: plan, run, open the folder."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import export, jobs, matches, reel, review

router = APIRouter()


@router.get("/api/matches/{match_id}/export")
def get_export(match_id: str):
    d = matches.match_dir(match_id)
    m = matches.load(match_id)
    if not m.get("clips"):
        raise HTTPException(400, "Review your clips first.")
    clips = m["clips"]
    rl = reel.of(m)
    by = matches.clips_by_index(m)
    reels = [{"rtype": k, "name": reel.RTYPE_NAMES[k], "count": len(r["entries"]), "total": reel.total_length(r, by) if r["entries"] else 0,
              "hook": by.get(r["entries"][0]["index"]) if r["entries"] else None,
              "sections": [] if reel.single_sequence(r) else reel.order_of(r)} for k, r in reel.all_of(m).items()]
    j = jobs.latest_for(match_id, "export")
    # One top-quality file per item (E1), which fits every app in export.platforms().
    return {"match": m, "clips": clips, "mbps": export.mbps(), "fits": [p["name"] for p in export.platforms().values()],
            "encoder": export.pick_encoder(),
            "reel": {"count": len(rl["entries"]), "total": reel.total_length(rl, by) if rl["entries"] else 0,
                     "hook": by.get(rl["entries"][0]["index"]) if rl["entries"] else None},
            "reels": reels, "active": rl["rtype"],
            # 2.2: the clips flagged "Export as clip" in Review start ticked
            "export_clips": [c["index"] for c in clips if review.export_on(c)],
            "job": j.to_dict() if j else None,
            "has_media": (d / "work" / "media.json").exists()}


class ExportIn(BaseModel):
    reel: bool = False
    reels: list[str] = []        # 2.1: which reels (batting / bowlfield / allround), one file each
    clips: list[int] | None = None   # None: the clips flagged "Export as clip" in Review
    encoder: str | None = None   # "libx264" to force the software encoder (retry after a Quick Sync failure)


@router.post("/api/matches/{match_id}/export/plan")
def export_plan(match_id: str, body: ExportIn):
    return export.plan(match_id, body.model_dump())


@router.post("/api/matches/{match_id}/export")
def start_export(match_id: str, body: ExportIn):
    what = body.model_dump()
    if not export.plan(match_id, what)["files"]:
        raise HTTPException(400, "Pick something to export.")
    enc = body.encoder if body.encoder in ("libx264", "h264_qsv") else None
    job = jobs.start("export", match_id, ["Export"], lambda j: export.run(j, match_id, what, enc))
    return job.to_dict()


@router.post("/api/matches/{match_id}/open-folder")
def open_folder(match_id: str):
    return {"path": export.open_folder(match_id)}
