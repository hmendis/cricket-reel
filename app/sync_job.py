"""The sync job: media prep → hit detection → alignment. Results go to the match folder."""
from __future__ import annotations

import numpy as np

from . import celebrate, config, fielding, hits, matches, media, scorecard, stance, sync
from .media import Cancelled

STEPS = ["Prepare the video (25 fps, preview, waveform)", "Find the wickets in the field", "Find bat hits in the audio",
         "Line up hits with the score sheet"]


CANDS_VERSION = 2  # bump when hits.detect changes, so stored candidates are recomputed


def detect_or_reuse(d, state: dict, params: dict) -> tuple[list[dict], bool]:
    """Hit candidates for this media and these detection settings. Re-uses work/candidates.json when both are
    unchanged (a re-sync after pinning or moving the start mark only needs the alignment). Returns (cands, reused)."""
    meta_file = d / "work" / "candidates.meta.json"
    key = {"version": CANDS_VERSION, "signature": state.get("signature"), "params": params}
    try:
        meta = config.read_json(meta_file)
        cands = config.read_json(d / "work" / "candidates.json")
    except ValueError:
        meta = cands = None
    if meta == key and isinstance(cands, list):
        return cands, True
    motion = np.load(d / "work" / "motion.npy")
    cands = hits.detect(d / "work" / "audio.wav", motion, state.get("motion_fps", 10), params)
    config.write_json_atomic(d / "work" / "candidates.json", cands, indent=None)
    config.write_json_atomic(meta_file, key)
    return cands, False


def run(job, match_id: str, batting_start: float | None, sensitivity: float | None = None):
    """Prep → hit detection → alignment. `sensitivity` None means: the one the last sync of this match used."""
    d = matches.match_dir(match_id)
    m = matches.load(match_id)
    sc = config.read_json(d / "scorecard.json")
    if not sc:
        raise media.MediaError("Check and save the score sheet first.")

    job.update(step=0, detail=f"{len(m['videos'])} video file(s)")
    state = media.prepare(d, m["videos"], lambda f: job.update(progress=f * 0.85), job.cancel)
    if job.cancel.is_set():
        raise Cancelled()

    kinds = matches.REEL_TYPES.get(m.get("highlights"), matches.REEL_TYPES["allround"])
    do_bat = "batting" in kinds
    field_inn = scorecard.innings_of(scorecard.Scorecard.model_validate(sc), "fielding")
    do_field = field_inn is not None and ("bowling" in kinds or "fielding" in kinds)
    fblock, t_max = None, None
    if do_field:
        # 2.1: the fielding phase is placed from the sheet and the celebrations, never from bat hits
        job.update(step=1, progress=0.86, detail="Listening for celebrations after the wickets…")
        fblock = field_block(d, m, sc, state)
        if job.cancel.is_set():
            raise Cancelled()
        if fblock["fielded_first"]:
            batting_start = fblock["bound"] if batting_start is None else batting_start
        else:
            t_max = fblock["bound"]
    if not do_bat:
        result = sync.no_batting(state["duration"])
        result["signature"], result["fielding"] = state["signature"], fblock
        config.write_json_atomic(d / "sync.json", result)
        with matches.edit(match_id) as m:
            matches.advance(m, "synced")
        return {"ok": True, "error": None, "stats": result["stats"], "fielding": fblock["counts"] if fblock else None}

    job.update(step=2, progress=0.88, detail="Listening for bat-on-ball sounds…")
    params = dict((config.read_json(config.CONFIG_DIR / "sync.json", {}) or {}).get("hits", {}))
    if sensitivity is None:
        sensitivity = (config.read_json(d / "sync.json", {}) or {}).get("sensitivity")
    if sensitivity is not None:
        params["sensitivity"] = max(0.0, min(1.0, float(sensitivity)))
    cands, reused = detect_or_reuse(d, state, params)
    job.update(progress=0.95, detail=f"{len(cands)} candidate hits" + (" (unchanged, reused)" if reused else ""))
    if job.cancel.is_set():
        raise Cancelled()

    job.update(step=3, detail=f"{len(cands)} candidate hits · aligning {sum(len(o['balls']) for o in sc['overs'])} deliveries")
    pins = {int(k): v for k, v in (m.get("sync_pins") or {}).items()}
    cands = with_stance(d, m, cands, job.cancel)
    result = sync.run(sc, cands, state["duration"], batting_start, pins, m.get("sync_anchors"), t_max=t_max)
    result["signature"] = state["signature"]
    result["fielding"] = fblock
    result["sensitivity"] = params.get("sensitivity", hits.DEFAULTS["sensitivity"])
    config.write_json_atomic(d / "sync.json", result)
    with matches.edit(match_id) as m:
        matches.advance(m, "synced" if result["ok"] else "sync")
    return {"ok": result["ok"], "error": result["error"], "stats": result.get("stats"), "fielding": fblock["counts"] if fblock else None}


def field_block(d, m: dict, sc: dict, state: dict) -> dict:
    """The fielding phase of sync.json: split, over starts and wickets, from the cached celebration features."""
    card = scorecard.Scorecard.model_validate(sc)
    inn = scorecard.innings_of(card, "fielding")
    F = celebrate.load_or_compute(d / "work", state["signature"], state.get("motion_fps", 10))
    user = m.get("fielding") or {}
    whole = m.get("highlights") == "bowlfield" and not user.get("has_batting")
    return fielding.run(scorecard.wickets(card), state, [v.get("name", "") for v in m.get("videos") or []],
                        inn.batted_first, user, F, whole=whole)


def refresh_fielding(match_id: str) -> dict:
    """Re-place the fielding phase after the user moved the split, flagged an over or confirmed a wicket. Fast:
    the celebration features are cached, so this needs no job."""
    d = matches.match_dir(match_id)
    res = config.read_json(d / "sync.json")
    sc = config.read_json(d / "scorecard.json")
    state = config.read_json(d / "work" / "media.json", {}) or {}
    if not res or not sc or not state.get("signature"):
        raise matches.MatchError("Run the sync first.", 400)
    res["fielding"] = field_block(d, matches.load(match_id), sc, state)
    config.write_json_atomic(d / "sync.json", res)
    return res["fielding"]


def with_stance(d, m: dict, cands: list[dict], cancel=None) -> list[dict]:
    """S3: add the 'you at the crease' value to each candidate when a reference frame is set (or a first shot
    is tagged). Without one, the candidates are returned unchanged."""
    ref = stance.reference_time(m)
    if ref is None:
        return cands
    sc = stance.scores(stance.ensure_frames(d / "work", cancel), ref)
    return stance.annotate(cands, sc)


def stance_overview(d, m: dict) -> dict | None:
    ref = stance.reference_time(m)
    if ref is None or not (d / "work" / stance.FILE).exists():
        return {"ref": ref, "moments": [], "auto": not (m.get("stance_ref") or {}).get("t")} if ref is not None else None
    sc = stance.scores(d / "work" / stance.FILE, ref)
    return {"ref": ref, "auto": (m.get("stance_ref") or {}).get("t") is None, "moments": stance.moments(sc)}


def realign_over(match_id: str, over_no: int) -> dict:
    """S4: after a pin changed in one over, re-line-up that over only (fast, no job)."""
    d = matches.match_dir(match_id)
    m = matches.load(match_id)
    prev = config.read_json(d / "sync.json")
    sc = config.read_json(d / "scorecard.json")
    cands = config.read_json(d / "work" / "candidates.json")
    if not prev or not sc or cands is None:
        raise matches.MatchError("Run the sync first.", 400)
    pins = {int(k): v for k, v in (m.get("sync_pins") or {}).items()}
    for i, t in sync.anchor_pins(sync.deliveries_from_scorecard(sc), m.get("sync_anchors")).items():
        pins.setdefault(i, t)
    try:
        res = sync.realign_over(sc, with_stance(d, m, cands), prev, over_no, pins)
    except ValueError as e:
        raise matches.MatchError(str(e), 409) from e
    config.write_json_atomic(d / "sync.json", res)
    return overview(match_id)


def overview(match_id: str) -> dict:
    """Everything the sync results screen needs."""
    d = matches.match_dir(match_id)
    res = config.read_json(d / "sync.json")
    state = config.read_json(d / "work" / "media.json", {}) or {}
    cands = config.read_json(d / "work" / "candidates.json", []) or []
    m = matches.load(match_id)
    return {"sync": res, "duration": state.get("duration"), "thumbs": state.get("thumbs"),
            "candidates": [{"t": c["t"], "s": c["s"]} for c in cands], "has_proxy": (d / "work" / "proxy.mp4").exists(),
            "stale": bool(res and state and res.get("signature") != media.signature(m["videos"])),
            "anchors": m.get("sync_anchors") or {}, "pins": m.get("sync_pins") or {},
            "stance": stance_overview(d, m),
            # 2.1: clips you added in Sync, the highlights this match makes, and what you set for the fielding phase
            "manual": m.get("manual_clips") or [], "highlights": m.get("highlights", "allround"), "field_user": m.get("fielding") or {},
            "offsets": state.get("offsets") or []}


def matches_signature(match_id: str) -> str:
    return media.signature(matches.load(match_id)["videos"])
