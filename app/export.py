"""Export: the highlight reel and/or picked clips, one top-quality file each, straight into exports/ (E1).

The same file uploads to TikTok, Instagram/Facebook Reels and YouTube Shorts, so there are no per-platform
variants or folders. Every file: 1080x1920, 25 fps, H.264 High at 40 Mbps (override "mbps" in
config/export.json), yuv420p 8-bit, BT.709 tagged (TV range), AAC 48 kHz 192 kbps, loudness normalised to
-14 LUFS (two-pass loudnorm), +faststart. The render keeps PCM audio, so AAC is encoded once (R10).
Quick Sync when available, else libx264 (CRF 16 with a bitrate cap).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from pathlib import Path

from . import config, matches, media, reel as reel_mod, render

# Only used to say which apps a file fits (their length limits change, so they can be overridden).
PLATFORMS = {
    "tiktok": {"name": "TikTok", "max_s": 600},
    "reels": {"name": "Reels", "max_s": 180},
    "shorts": {"name": "Shorts", "max_s": 180},
}
MBPS = 40
W, H = 1080, 1920
BT709 = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]
FINAL = "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p"


def platforms() -> dict:
    """Length limits per app, with optional overrides from config/export.json."""
    over = config.read_json(config.CONFIG_DIR / "export.json", {}) or {}
    return {k: {**v, **(over.get(k) or {})} for k, v in PLATFORMS.items()}


def mbps() -> int:
    over = config.read_json(config.CONFIG_DIR / "export.json", {}) or {}
    return int(over.get("mbps", MBPS))


def fits(seconds: float) -> list[str]:
    return [p["name"] for p in platforms().values() if not p.get("max_s") or seconds <= p["max_s"]]


def encoder_args(mbps: int, encoder: str) -> list[str]:
    if encoder == "h264_qsv":
        return ["-c:v", "h264_qsv", "-profile:v", "high", "-preset", "slower", "-b:v", f"{mbps}M",
                "-maxrate", f"{int(mbps * 1.4)}M", "-bufsize", f"{mbps * 2}M", "-pix_fmt", "nv12", *BT709]
    return ["-c:v", "libx264", "-profile:v", "high", "-preset", "medium", "-crf", "16",
            "-maxrate", f"{int(mbps * 1.4)}M", "-bufsize", f"{mbps * 2}M", "-pix_fmt", "yuv420p", *BT709]


def pick_encoder() -> str:
    pref = config.load_settings().get("encoder", "auto")
    return "libx264" if pref == "x264" else media.h264_encoder()


# ---------- source mapping ----------
def source_mapper(match_dir: Path, m: dict):
    """(start, length) on the match timeline → pieces of the source files (25 fps working copies for VFR files)."""
    state = config.read_json(match_dir / "work" / "media.json", {}) or {}
    offs = state.get("offsets") or []
    if not offs:
        raise media.MediaError("Run the sync first (it prepares the video).")
    files = []
    copies = state.get("working_copies")
    for i, o in enumerate(offs):
        cfr = match_dir / "work" / f"cfr_{i + 1:02d}.mp4"
        use_cfr = cfr.exists() and (copies is None or i + 1 in copies)  # older preps made copies for any non-25 fps
        src = Path(o["path"]) if o.get("path") else match_dir / o["file"]
        files.append((cfr if use_cfr else src, o["start"], o["duration"]))
    for f, _, _ in files:
        if not f.exists():
            raise media.MediaError(f"Source video missing: {f}. Find it again on the import screen.")

    def segs(start: float, length: float):
        out, t, end = [], start, start + length
        for f, s0, dur in files:
            s1 = s0 + dur
            if t < s1 and end > s0:
                a, b = max(t, s0), min(end, s1)
                if b - a > 0.02:
                    out.append((f, a - s0, b - a))
        return out or [(files[-1][0], max(0.0, files[-1][2] - length), length)]
    return segs


# ---------- naming ----------
def result_slug(c: dict) -> str:
    code = c["code"].strip().lower()
    if c["kind"] == "wicket":
        return "wicket"
    if c["kind"] == "extra":
        return re.sub(r"[^a-z]", "", c["label"].lower()) or "extra"
    n = int(code) if code.isdigit() else 0
    return "dot" if n == 0 else f"{n}run{'s' if n > 1 else ''}"


def match_slug(m: dict, sc: dict | None) -> str:
    mm = (sc or {}).get("match") or {}
    date = mm.get("date") or m["created"][:10]
    slug = lambda s: re.sub(r"[^\w]+", "-", s).strip("-")  # noqa: E731
    return f"{date}_{slug(mm.get('team_us') or 'Us')}-v-{slug(mm.get('team_them') or 'Them')}"


def reel_name(m: dict, sc: dict | None, rtype: str = "batting") -> str:
    """2.1: named after what's in it: ..._batting_reel.mp4, ..._bowling-fielding_reel.mp4, ..._allround_reel.mp4."""
    return f"{match_slug(m, sc)}_{reel_mod.RTYPE_SLUG.get(rtype, 'batting')}_reel.mp4"


def clip_name(c: dict) -> str:
    """Batting balls as in 2.0 (over3_ball02_4runs.mp4). 2.1: wickets in the field say their innings and kind
    (their-over12_ball01_bowling_bowled.mp4); clips added in Sync say their kind, label and time."""
    if c.get("source") == "manual":
        label = re.sub(r"[^a-z0-9]+", "-", (c.get("label") or "clip").lower()).strip("-") or "clip"
        return f"{c.get('role', 'other')}_{label}_{int(c['t'] // 60)}m{int(c['t'] % 60):02d}s.mp4"
    if c.get("wid"):
        how = re.sub(r"[^a-z]+", "-", c["label"].split("·")[-1].strip().lower()).strip("-") or "wicket"
        return f"their-over{c['over']}_ball{c['ball']:02d}_{c.get('role', 'fielding')}_{how}.mp4"
    return f"over{c['over']}_ball{c['ball']:02d}_{result_slug(c)}.mp4"


# ---------- plan ----------
def plan(match_id: str, what: dict) -> dict:
    """what = {reels: [rtype...], reel: bool (the active reel), clips: [index...]} → the files that will be written,
    one per item, into exports/."""
    d = matches.match_dir(match_id)
    m = matches.load(match_id)
    sc = config.read_json(d / "scorecard.json")
    clips = matches.clips_by_index(m)
    rtypes = list(dict.fromkeys(what.get("reels") or []))
    if what.get("reel") and not rtypes:
        rtypes = [reel_mod.of(m)["rtype"]]
    files, total = [], 0
    for rt in rtypes:
        if rt not in (m.get("reels") or {}) and rt != reel_mod.of(m)["rtype"]:
            continue
        rl = reel_mod.of(m, rt)
        if not rl["entries"]:
            continue
        tl = reel_mod.total_length(rl, clips)
        total = total or tl
        ok = fits(tl)
        files.append({"kind": "reel", "rtype": rt, "name": reel_name(m, sc, rt), "folder": "", "duration": tl, "fits": ok,
                      "warning": None if len(ok) == len(PLATFORMS) else f"{tl:.1f} s is too long for " +
                      ", ".join(p["name"] for p in platforms().values() if p["name"] not in ok)})
    picked = what.get("clips")
    if picked is None and what.get("reel"):  # a 2.0 request ("the reel") meant the reel only
        picked = []
    if picked is None:  # 2.2: by default, the clips flagged "Export as clip" in Review
        from .review import export_on
        picked = [c["index"] for c in m.get("clips") or [] if export_on(c)]
    for i in dict.fromkeys(picked):
        if i in clips:
            c = clips[i]
            dur = round(c["before"] + c["after"], 2)
            files.append({"kind": "clip", "index": i, "name": clip_name(c), "folder": "", "duration": dur,
                          "fits": fits(dur), "warning": None})
    return {"files": files, "reel_total": total, "encoder": pick_encoder(), "mbps": mbps(), "folder": "exports"}


# ---------- run ----------
def _loudnorm(tmp: Path, out: Path, cancel: threading.Event, seconds: float = 60.0):
    """Two-pass loudnorm to -14 LUFS / -1.5 dBTP on the finished file; video is copied, not re-encoded.
    Both passes can be cancelled and are stopped if they take far longer than the file is long."""
    limit = max(120.0, seconds * 4)
    r = media.run([media.ffmpeg(), "-hide_banner", "-nostats", "-i", str(tmp), "-vn", "-af",
                   "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], cancel=cancel, timeout=limit)
    js = r.stderr[r.stderr.rfind("{"): r.stderr.rfind("}") + 1]
    try:
        ms = json.loads(js)
        af = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={ms['input_i']}:measured_TP={ms['input_tp']}:"
              f"measured_LRA={ms['input_lra']}:measured_thresh={ms['input_thresh']}:offset={ms['target_offset']}:linear=true")
    except (ValueError, KeyError):
        af = "loudnorm=I=-14:TP=-1.5:LRA=11"
    if cancel.is_set():
        raise media.Cancelled()
    # Stamp BT.709 / TV range into the H.264 stream itself (VUI) so every player and platform reads it,
    # whichever encoder made the file.
    vui = "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1:video_full_range_flag=0"
    media.run([media.ffmpeg(), "-v", "error", "-y", "-i", str(tmp), "-map", "0:v", "-map", "0:a", "-c:v", "copy",
               "-bsf:v", vui, *BT709, "-af", af, "-ar", "48000", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)],
              cancel=cancel, timeout=limit)


def run(job, match_id: str, what: dict, encoder: str | None = None):
    d = matches.match_dir(match_id)
    m = matches.load(match_id)
    p = plan(match_id, what)
    if not p["files"]:
        raise media.MediaError("Pick the reel or at least one clip to export.")
    enc = encoder or p["encoder"]
    clips = matches.clips_by_index(m)
    rl = reel_mod.of(m)
    segs = source_mapper(d, m)
    work = d / "work" / "export"
    files = [{**f, "status": "waiting", "progress": 0.0, "error": None, "size": None} for f in p["files"]]
    job.result = {"files": files, "encoder": enc, "folder": str(d / "exports")}
    rate = p["mbps"]
    duration = (config.read_json(d / "work" / "media.json", {}) or {}).get("duration")
    n = len(files)
    for k, f in enumerate(files):
        if job.cancel.is_set():
            f["status"] = "cancelled"
            continue
        f["status"] = "rendering"
        job.update(step=0, detail=f"{k + 1} of {n}: {f['name']}")
        dest_dir = d / "exports"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f["name"]
        try:
            t0 = time.time()
            if f["kind"] == "reel":
                r = reel_mod.of(m, f.get("rtype"))
            else:  # a single clip: its label, no hook/outro/freeze/transitions
                r = {**rl, "entries": [{"uid": "x", "index": f["index"], "trans": None}], "hook_text": "", "outro_text": "", "freeze": False}
            tmp = work / f"render_{k}.mov"  # PCM audio inside: the only AAC encode is the final one (R10)
            part = dest.with_suffix(".part.mp4")
            cmd, total = render.build_command(
                r, clips, segs, tmp, work, (W, H), None,  # 2.2: no music, also for reels that have a file
                encode_args=encoder_args(rate, enc), audio_args=["-c:a", "pcm_s16le"], final_filter=FINAL,
                duration=duration)
            try:
                media.run(cmd, total=total, on_progress=lambda fr, f=f, k=k: (f.__setitem__("progress", round(fr * 0.9, 3)),
                                                                             job.update(progress=(k + fr * 0.9) / n)),
                          cancel=job.cancel, cwd=work)
                f["status"] = "loudness"
                _loudnorm(tmp, part, job.cancel, total)
                config.replace_with_retry(part, dest)
            finally:
                tmp.unlink(missing_ok=True)
                part.unlink(missing_ok=True)
            f.update(status="done", progress=1.0, size=dest.stat().st_size, seconds=round(time.time() - t0, 1), path=str(dest))
        except media.Cancelled:
            f["status"] = "cancelled"
            break
        except (media.MediaError, OSError) as e:
            f.update(status="failed", error=str(getattr(e, "message", None) or e) or "FFmpeg failed")
        job.update(progress=(k + 1) / n)
    for leftover in list(work.glob("render_*.mp4")) + list(work.glob("render_*.mov")):
        leftover.unlink(missing_ok=True)
    for f in files:
        if f["status"] == "waiting":
            f["status"] = "cancelled"
    if any(f["status"] == "done" for f in files):
        with matches.edit(match_id) as m:
            matches.advance(m, "exported")
            ok = [f for f in files if f["status"] == "done"]
            m.setdefault("exports", []).append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "files": [f["name"] for f in ok],
                                                "items": [{k: f.get(k) for k in ("name", "kind", "index", "rtype")} for f in ok]})
    return job.result


def open_folder(match_id: str) -> str:
    d = matches.match_dir(match_id) / "exports"
    d.mkdir(parents=True, exist_ok=True)
    if hasattr(os, "startfile"):
        os.startfile(str(d))  # noqa: S606 - opens Explorer on the user's own folder
    return str(d)
