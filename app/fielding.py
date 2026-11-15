"""The fielding phase (2.1): where it is in the recording, where each over starts and where each wicket is.

No bat-hit alignment here: from the field the hit detector hears about 60 false hits a minute. Instead:
1. Phase split: guessed from which side batted first and the gap between the camera's files; the user can drag it.
2. Over starts: overs the user hasn't flagged ("first ball of over N") are spread evenly between flags, about 2:05
   an over with a longer break after overs 4, 8 and 12. Each flag re-anchors the overs near it.
3. Wickets: the ball's place in its over gives a timing guess; celebrate.find looks for the noise after it within one
   ball either side, per ball, so wickets close together still get one celebration each.
"""
from __future__ import annotations

import re
from datetime import datetime

from . import celebrate

N_OVERS = 16
OVER_LEN = 125.0            # seconds per over in the field: about 2:00-2:10 on the first real match (11/11), not the 2:24 first assumed
BREAK = 60.0                # extra seconds after overs 4, 8 and 12 (drinks, batter change)
BREAK_AFTER = (4, 8, 12)
END_MARGIN = 15.0           # the last ball is this long before the end of the phase
WICKET_BEFORE_CELEBRATION = 1.5  # the wicket happens about this long before the noise starts
CLIP_BEFORE = 3.0           # clip starts about 3 s before the delivery...
CLIP_MAX = 8.0              # ...and runs until the celebration fades, at most 8 s
RESPREAD_MIN = 5.0          # confirming a wicket this far from its guess moves the unconfirmed ones near it
SPLIT_GAP_MIN = 60.0        # a gap between two files longer than this is probably the innings break
FILE_TIME = re.compile(r"(\d{8})_(\d{6})")


def over_weights(n: int = N_OVERS) -> list[float]:
    """Cumulative over units: over k starts at cum[k-1]; a break adds BREAK/OVER_LEN of an over."""
    cum = [0.0]
    for k in range(1, n + 1):
        cum.append(cum[-1] + 1 + (BREAK / OVER_LEN if k in BREAK_AFTER and k < n else 0))
    return cum


def expected_length(n: int = N_OVERS) -> float:
    return over_weights(n)[n] * OVER_LEN


def _file_start(name: str) -> datetime | None:
    m = FILE_TIME.search(name or "")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def guess_split(offsets: list[dict], names: list[str], duration: float, fielded_first: bool) -> dict:
    """Where fielding ends and batting starts (or the other way round). offsets: media.json offsets (start, duration
    per file); names: the camera's file names, which carry the recording time (VID_20261111_190214_409.mp4)."""
    seams = []
    for k in range(1, len(offsets)):
        prev, cur = offsets[k - 1], offsets[k]
        a, b = _file_start(names[k - 1] if k - 1 < len(names) else ""), _file_start(names[k] if k < len(names) else "")
        gap = (b - a).total_seconds() - prev["duration"] if a and b else None
        seams.append({"t": cur["start"], "gap": gap})
    mid = [s for s in seams if 0.25 * duration <= s["t"] <= 0.75 * duration]
    gaps = [s for s in mid if s["gap"] is not None and s["gap"] > SPLIT_GAP_MIN]
    if gaps:
        s = max(gaps, key=lambda s: s["gap"])
        return {"bound": round(s["t"], 1), "source": "gap", "gap": round(s["gap"], 1)}
    if mid:
        s = min(mid, key=lambda s: abs(s["t"] - duration / 2))
        return {"bound": round(s["t"], 1), "source": "seam", "gap": s["gap"]}
    return {"bound": round(duration / 2, 1), "source": "middle", "gap": None}


def phase_range(bound: float, duration: float, fielded_first: bool) -> tuple[float, float]:
    return (0.0, bound) if fielded_first else (bound, duration)


def default_ends(rng: tuple[float, float]) -> tuple[float, float]:
    """The first ball of over 1 and the last ball of over 16 when nothing is flagged: the innings is assumed to end just
    before the end of its phase (head-cam recordings start with warm-up, not with play)."""
    end = rng[1] - END_MARGIN
    return max(rng[0], end - expected_length()), end


def spread_overs(start: float, end: float, flags: dict | None = None, n: int = N_OVERS) -> list[dict]:
    """Start time and length of every over. Flagged overs start exactly at their flag; the overs between two
    anchors are spread evenly, weighted for the longer breaks."""
    cum = over_weights(n)
    flags = {int(k): float(v) for k, v in (flags or {}).items() if 1 <= int(k) <= n}
    anchors = [(0.0, flags.get(1, start))]
    anchors += [(cum[k - 1], t) for k, t in sorted(flags.items()) if k > 1]
    last = cum[n - 1] + 1
    if anchors[-1][0] < last:
        anchors.append((last, max(end, anchors[-1][1] + 1)))
    out = []
    for k in range(1, n + 1):
        u = cum[k - 1]
        a, b = anchors[0], anchors[-1]
        for j in range(len(anchors) - 1):
            if anchors[j][0] <= u < anchors[j + 1][0]:
                a, b = anchors[j], anchors[j + 1]
                break
        scale = (b[1] - a[1]) / (b[0] - a[0]) if b[0] != a[0] else OVER_LEN
        out.append({"n": k, "s": round(a[1] + (u - a[0]) * scale, 2), "len": round(scale, 2), "set": k in flags})
    return out


def ball_time(over: dict, ball: int, n_balls: int) -> float:
    """The moment of ball `ball` (1-based) of an over spread over `len` seconds."""
    return over["s"] + (ball - 0.35) * over["len"] / max(1, n_balls)


def place_wickets(wkts: list[dict], overs: list[dict], F: dict | None, confirmed: dict | None = None,
                  shift: dict | None = None) -> list[dict]:
    """Each wicket's time and confidence: confirmed (the user OK'd it), celebration (the timing guess and the noise
    agree) or timing (guess only). Wickets are handled in order, and each one's celebration must come after the
    previous wicket's, so two wickets in one over don't share a celebration."""
    confirmed = {str(k): float(v) for k, v in (confirmed or {}).items()}
    shift = {int(k): float(v) for k, v in (shift or {}).items()}
    by_n = {o["n"]: o for o in overs}
    out, after = [], 0.0
    for w in wkts:
        o = by_n.get(w["over"])
        if not o:
            continue
        bl = o["len"] / max(1, w["balls_in_over"])
        guess = ball_time(o, w["ball"], w["balls_in_over"]) + shift.get(w["over"], 0.0)
        e = {**w, "t_guess": round(guess, 2), "ball_len": round(bl, 2)}
        if w["id"] in confirmed:
            t, c = confirmed[w["id"]], None
            e.update(conf="confirmed", why="Confirmed by you")
            if F is not None and len(F["voice_db"]):
                c = celebrate.at(F, t + WICKET_BEFORE_CELEBRATION)
        else:
            c = celebrate.find(F, max(after, guess - bl + 0.5), guess + bl + 4.0) if F is not None and len(F["voice_db"]) else None
            if c and c["db"] >= celebrate.MIN_DB:
                t = c["t"] - WICKET_BEFORE_CELEBRATION
                e.update(conf="celebration", why=f"Voice +{c['db']} dB over 4 s" + (" · pitch up" if c["pitch"] > 50 else "")
                         + (f" · {c['claps']} clap{'s' * (c['claps'] != 1)}" if c["claps"] else "") + (" · head moving" if c["motion"] > 1.3 else ""))
            else:
                t = guess
                e.update(conf="timing", why="No clear celebration" + (f" (voice +{c['db']} dB)" if c else "") + ". Placed from the ball order only.")
        e["t"] = round(t, 2)
        e["celebration"] = c
        fade = celebrate.fade(F, t + WICKET_BEFORE_CELEBRATION) if F is not None and len(F["voice_db"]) and c else 3.0
        e["before"] = CLIP_BEFORE
        e["after"] = round(min(CLIP_MAX - CLIP_BEFORE, max(3.0, WICKET_BEFORE_CELEBRATION + fade)), 2)
        after = t + WICKET_BEFORE_CELEBRATION + 2.0
        out.append(e)
    return out


def respread(shift: dict, wicket: dict, t: float) -> dict:
    """After the user confirms a wicket at t: if it's more than RESPREAD_MIN from its guess, move the unconfirmed
    wickets of that over by the same amount and those of the next over by half of it."""
    shift = {int(k): float(v) for k, v in (shift or {}).items()}
    delta = t - wicket["t_guess"]
    if abs(delta) > RESPREAD_MIN:
        o = wicket["over"]
        shift[o] = shift.get(o, 0.0) + delta
        if o < N_OVERS:
            shift[o + 1] = shift.get(o + 1, 0.0) + delta / 2
    return {str(k): round(v, 2) for k, v in shift.items()}


def run(wkts: list[dict], state: dict, names: list[str], fielded_first: bool, user: dict | None, F: dict | None,
        whole: bool = False) -> dict:
    """The fielding block of sync.json. user: match.json "fielding" (bound, flags, confirmed, shift) - all optional.
    whole: the reel is Bowling + Fielding and the user hasn't said the video has batting too, so the whole recording
    is the fielding phase (no split to guess)."""
    user = user or {}
    duration = state.get("duration") or 0.0
    if whole:
        split = {"bound": round(duration if fielded_first else 0.0, 1), "source": "whole", "gap": None}
        bound = split["bound"]
    else:
        split = guess_split(state.get("offsets") or [], names, duration, fielded_first)
        bound = float(user["bound"]) if user.get("bound") is not None else split["bound"]
    rng = phase_range(bound, duration, fielded_first)
    start, end = default_ends(rng)
    overs = spread_overs(start, end, user.get("flags"))
    placed = place_wickets(wkts, overs, F, user.get("confirmed"), user.get("shift"))
    return {"version": 1, "fielded_first": fielded_first, "bound": round(bound, 1), "split": split, "whole": whole,
            "bound_set": not whole and user.get("bound") is not None,
            "range": [round(rng[0], 1), round(rng[1], 1)], "start": round(start, 1), "end": round(end, 1),
            "overs": overs, "wickets": placed,
            "counts": {c: sum(w["conf"] == c for w in placed) for c in ("confirmed", "celebration", "timing")}}
