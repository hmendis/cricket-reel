"""Align the score sheet's deliveries to bat-hit candidates with dynamic programming.

Every delivery of the pair's overs (mine and my partner's) is placed in order on the timeline. The
best placement maximises candidate strength (weighted by how loud a hit we expect for that result)
while keeping the gaps between balls plausible: a typical gap within an over, a longer gap at an over
change, both learned from the match. Deliveries with no good candidate are skipped (penalised) and get
an interpolated time, marked low confidence ("needs check").
"""
from __future__ import annotations

import math
from datetime import datetime

import numpy as np

from .scorecard import parse_code

PRIORS = {"gap_ball": 22.0, "gap_over_extra": 25.0}
GAP_SIGMA = 0.35       # spread of log(gap / expected)
GAP_WEIGHT = 0.18
SKIP_PENALTY = 0.4     # cost of leaving a delivery without a candidate (weaker candidates are skipped)
MAX_SKIP = 3           # consecutive deliveries that may be skipped


def deliveries_from_scorecard(sc: dict) -> list[dict]:
    out = []
    for o in sc["overs"]:
        for bi, b in enumerate(o["balls"]):
            out.append({"over": o["number"], "ball": bi + 1, "facer": b["facer"], "code": b["code"], "first_of_over": bi == 0})
    return out


def expected_hit(d: dict) -> float:
    """How strongly we expect this delivery to show up (sound + movement), 0..1."""
    p = parse_code(d["code"])
    c = d["code"].strip().lower()
    if p["kind"] in ("runs", "big"):
        w = 1.0 if p["bat"] > 0 else 0.7
    elif p["kind"] == "wicket":
        w = 0.4 if c.startswith("b") else 0.8
    elif p["kind"] == "extra":
        w = 0.8 if c.startswith("nb") else 0.5
    else:
        w = 0.6
    return w * (1.0 if d["facer"] == "me" else 0.75)


def _expected_gap(dels, i_prev, i, g_ball, g_over):
    return sum(g_ball + (g_over if dels[k]["first_of_over"] else 0.0) for k in range(i_prev + 1, i + 1))


# (audio, motion) weights. Before every delivery the camera (on my head) is still - in my stance, or
# watching from the non-striker's end - so motion counts for both. My own hits are close to the
# camera mic, so the sound counts a little more for them.
MIX = {"me": (0.55, 0.45), "partner": (0.45, 0.55)}


STANCE_WEIGHT = 0.3  # S3: "you at the crease" just before a sound makes it likelier to be your ball, unlikelier your partner's


def cand_strength(c: dict, facer: str) -> float:
    if "audio" not in c or "motion" not in c:
        return c["s"]
    wa, wm = MIX[facer]
    s = wa * c["audio"] + wm * c["motion"]
    if "stance" in c:
        s += STANCE_WEIGHT * c["stance"] * (1 if facer == "me" else -1)
    return s


PIN_WINDOW = 3.0  # how far before a pin the batting can start
PIN_SNAP = 0.12   # a pinned ball lands exactly on the pin, or on a bat sound this close to it (3 frames)
NEG = -1e9


def _window(tarr: np.ndarray, mu: float):
    """For every candidate: which earlier candidates are a plausible previous ball for an expected gap mu, and the
    gap cost of each, as (has_any, (m x width) indices, (m x width) cost with +inf outside the window)."""
    m = len(tarr)
    lo_gap, hi_gap = max(5.0, 0.35 * mu), 2.6 * mu
    lo = np.searchsorted(tarr, tarr - hi_gap, "left")
    hi = np.searchsorted(tarr, tarr - lo_gap, "right")
    width = int((hi - lo).max())
    if width <= 0:
        return False
    idx = lo[:, None] + np.arange(width)[None, :]
    inwin = idx < hi[:, None]
    idxc = np.minimum(idx, m - 1)
    dt = np.where(inwin, tarr[:, None] - tarr[idxc], mu)
    cost = np.where(inwin, GAP_WEIGHT * (np.log(dt / mu) / GAP_SIGMA) ** 2, np.inf)
    return hi > lo, idxc, cost


def _align(dels, cands, t_min, t_max, g_ball, g_over, pins=None):
    """Best placement of every delivery on a candidate (or skipped), as {delivery index: candidate index}.

    Dynamic programming over (delivery, candidate). For each delivery and each possible previous matched
    delivery (up to MAX_SKIP skipped in between), all candidates are scored at once: a (candidates x window)
    matrix of the plausible previous candidates and their gap cost, maximised per row. Candidates outside
    t_min..t_max are dropped first. Back-pointers live in two int arrays.
    """
    pins = pins or {}
    n = len(dels)
    t_all = np.array([c["t"] for c in cands], float)
    keep = np.where((t_all >= t_min) & (t_all <= t_max))[0]
    if n == 0 or len(keep) == 0:
        return {}, NEG
    tarr = t_all[keep]
    m = len(tarr)
    a = np.array([expected_hit(d) for d in dels])
    strength = {f: np.array([cand_strength(cands[k], f) for k in keep]) for f in MIX}
    best = np.full((n, m), NEG)
    back_i = np.full((n, m), -1, np.int32)   # previous delivery (-1 = this is the first matched one)
    back_j = np.full((n, m), -1, np.int32)
    rows = np.arange(m)
    windows: dict[float, tuple | bool] = {}
    pinned = sorted(pins)

    def skips_pin(lo, hi):  # is any pinned delivery strictly between lo and hi?
        return any(lo < k < hi for k in pinned)

    for i in range(n):
        valid = np.abs(tarr - pins[i]) <= PIN_SNAP if i in pins else np.ones(m, bool)
        gain = a[i] * strength[dels[i]["facer"]]
        # start: deliveries 0..i-1 skipped
        if i <= MAX_SKIP and not skips_pin(-1, i):
            start = np.where(valid, gain - SKIP_PENALTY * i, NEG)
            better = start > best[i]
            best[i][better] = start[better]
            back_i[i][better] = -1
        for ip in range(max(0, i - 1 - MAX_SKIP), i):
            if skips_pin(ip, i):
                continue
            prev = best[ip]
            if prev.max() <= NEG / 2:
                continue
            mu = _expected_gap(dels, ip, i, g_ball, g_over)
            win = windows.get(mu)
            if win is None:  # the expected gap only takes a few values (balls skipped, over change): build once each
                win = windows[mu] = _window(tarr, mu)
            if win is False:
                continue
            has, idxc, cost = win
            tot = prev[idxc] - cost
            k = np.argmax(tot, axis=1)
            v = tot[rows, k] + gain - SKIP_PENALTY * (i - ip - 1)
            upd = valid & has & (v > best[i])
            best[i][upd] = v[upd]
            back_i[i][upd] = ip
            back_j[i][upd] = idxc[rows, k][upd]
    # end: deliveries after i skipped
    end_score = best - SKIP_PENALTY * (n - 1 - np.arange(n))[:, None]
    end_score[np.arange(n) < n - 1 - MAX_SKIP] = NEG
    for i in range(n):
        if skips_pin(i, n):
            end_score[i] = NEG
    i, j = np.unravel_index(int(np.argmax(end_score)), end_score.shape)
    if end_score[i, j] <= NEG / 2:
        return {}, NEG
    total = float(end_score[i, j])
    assign = {}
    i, j = int(i), int(j)
    while True:
        assign[i] = int(keep[j])
        if back_i[i, j] < 0:
            break
        i, j = int(back_i[i, j]), int(back_j[i, j])
    return assign, total


def _learn_gaps(dels, assign, cands, g_ball, g_over):
    within, overs = [], []
    idx = sorted(assign)
    for a, b in zip(idx, idx[1:]):
        if b != a + 1:
            continue
        dt = cands[assign[b]]["t"] - cands[assign[a]]["t"]
        (overs if dels[b]["first_of_over"] else within).append(dt)
    nb = float(np.clip(np.median(within), 12, 45)) if len(within) >= 4 else g_ball
    no = float(np.clip(np.median(overs) - nb, 0, 120)) if len(overs) >= 1 else g_over
    return nb, no


def anchor_pins(dels: list[dict], anchors: dict | None) -> dict[int, float]:
    """S2: your tagged first and last shot become pins on your first and last delivery."""
    anchors = anchors or {}
    mine = [i for i, d in enumerate(dels) if d["facer"] == "me"]
    out = {}
    if mine and anchors.get("first") is not None:
        out[mine[0]] = float(anchors["first"])
    if mine and anchors.get("last") is not None:
        out[mine[-1]] = float(anchors["last"])
    return out


def _with_pin_cands(cands, pins):
    cands = list(cands)
    for t in pins.values():  # make sure every pin has at least one candidate to land on
        if not any(abs(c["t"] - t) <= PIN_SNAP for c in cands):
            cands.append({"t": t, "s": 0.6, "audio": 0.6, "motion": 0.6, "synthetic": True})
    return sorted(cands, key=lambda c: c["t"])


def over_slots(dels: list[dict], start: float | None, g_ball: float, g_over: float) -> list[dict]:
    """S1: an estimated time slot per over, from the batting start, the balls in each over and the learned gaps."""
    if start is None:
        return []
    out, t = [], float(start)
    for d in dels:
        if d["first_of_over"]:
            balls = sum(1 for x in dels if x["over"] == d["over"])
            out.append({"over": d["over"], "start": round(t, 1), "end": round(t + balls * g_ball + g_over, 1)})
            t = out[-1]["end"]
    return out


def _entry(d, i, times, assign, cands, ts, pins, g_ball, g_over, dels) -> dict:
    j = assign.get(i)
    pc = parse_code(d["code"])
    entry = {**d, "index": i, "t": round(times[i], 3) if times[i] is not None else None, "candidate": None,
             "strength": None, "conf": "low", "why": "no_hit", "kind": pc["kind"], "label": pc["label"]}
    if j is not None:
        s = cand_strength(cands[j], d["facer"])
        conf, why = ("high", "pinned") if i in pins else confidence(dels, i, assign, cands, ts, g_ball, g_over)
        entry.update(candidate=j, strength=round(s, 3), conf=conf, why=why, pinned=pins.get(i))
    return entry


def _summary(result: dict, dels: list[dict], times: list) -> None:
    """S1 markers on a finished result: over slots, first and last ball."""
    start = result.get("batting_start") if result.get("batting_start") is not None else result.get("auto_start")
    result["slots"] = over_slots(dels, start, result["gap_ball"], result["gap_over_extra"])
    known = [t for t in times if t is not None]
    result["first_ball"] = round(known[0], 3) if known else None
    result["last_ball"] = round(known[-1], 3) if known else None


def run(sc: dict, cands: list[dict], duration: float, batting_start: float | None = None,
        pins: dict[int, float] | None = None, anchors: dict | None = None, t_max: float | None = None) -> dict:
    """pins: {delivery index: time} the user has confirmed; those balls land there (or on a sound within PIN_SNAP).
    anchors: {"first": t, "last": t} - your tagged first and last shot (S2).
    t_max: the end of the batting phase when we batted first (2.1); bat sounds after it are ignored."""
    dels = deliveries_from_scorecard(sc)
    n = len(dels)
    pins = {int(k): float(v) for k, v in (pins or {}).items() if 0 <= int(k) < n}
    for i, t in anchor_pins(dels, anchors).items():
        pins.setdefault(i, t)  # a ball you pinned yourself wins over the tag
    cands = _with_pin_cands(cands, pins)
    if pins and batting_start is not None:
        batting_start = min(batting_start, min(pins.values()) - PIN_WINDOW)
    result = {"version": 1, "created": datetime.now().isoformat(timespec="seconds"), "batting_start": batting_start,
              "duration": duration, "candidates": len(cands), "ok": False, "error": None, "deliveries": [],
              "pins": {str(k): v for k, v in pins.items()}, "anchors": anchors or {}}
    if n == 0:
        result["error"] = "The score sheet has no deliveries for your pair."
        return result
    t_min = max(0.0, (batting_start or 0.0) - 2.0)
    g_ball, g_over = PRIORS["gap_ball"], PRIORS["gap_over_extra"]
    assign = {}
    if len(cands) >= max(3, n // 3):
        for _ in range(3):
            assign, _total = _align(dels, cands, t_min, t_max or duration, g_ball, g_over, pins)
            nb, no = _learn_gaps(dels, assign, cands, g_ball, g_over)
            if abs(nb - g_ball) < 0.5 and abs(no - g_over) < 1:
                break
            g_ball, g_over = nb, no
    result["gap_ball"], result["gap_over_extra"] = round(g_ball, 1), round(g_over, 1)

    times = interpolate_times(dels, assign, cands, g_ball, g_over, duration)
    ts = np.array([c["t"] for c in cands]) if cands else np.zeros(0)
    result["deliveries"] = [_entry(d, i, times, assign, cands, ts, pins, g_ball, g_over, dels) for i, d in enumerate(dels)]

    result["stats"] = stats(result["deliveries"], assign)
    matched = sorted(assign)
    first = min((times[i] for i in matched), default=None)
    result["auto_start"] = round(max(0.0, first - g_ball), 1) if first is not None else None
    # Head-cam recordings usually start before play (walking in, warming up). If the first ball landed in
    # the first minute and no start was marked, the alignment may be counting warm-up noise as balls.
    result["start_warning"] = bool(batting_start is None and not pins and first is not None and first < 60)
    st = result["stats"]
    if len(assign) < max(2, int(MIN_MATCHED * n)) or (st["mine"] and st["mine_matched"] < MIN_MINE_MATCHED * st["mine"]):
        result["error"] = (f"Only {len(assign)} of {n} deliveries could be matched to bat sounds "
                           f"({len(cands)} candidate sounds found).")
    else:
        result["ok"] = True
    _summary(result, dels, times)
    return result


def realign_over(sc: dict, cands: list[dict], prev: dict, over_no: int, pins: dict[int, float]) -> dict:
    """S4: re-line-up only one over (after a pin in it changed). Every other over keeps exactly the times and
    confidence it had; the over is fitted between the last ball before it and the first ball after it."""
    dels = deliveries_from_scorecard(sc)
    n = len(dels)
    pins = {int(k): float(v) for k, v in (pins or {}).items() if 0 <= int(k) < n}
    cands = _with_pin_cands(cands, pins)
    ts = np.array([c["t"] for c in cands]) if cands else np.zeros(0)
    g_ball, g_over = prev.get("gap_ball", PRIORS["gap_ball"]), prev.get("gap_over_extra", PRIORS["gap_over_extra"])
    old = prev["deliveries"]
    idx = [i for i, d in enumerate(dels) if d["over"] == over_no]
    if not idx or len(old) != n:
        raise ValueError("The score sheet changed since the last sync. Run the whole sync again.")

    def find(t):
        if t is None or not len(ts):
            return None
        j = int(np.argmin(np.abs(ts - t)))
        return j if abs(ts[j] - t) < 1e-3 else None

    assign = {}
    for d in old:  # the other overs keep their sounds
        if d["over"] != over_no and d.get("candidate") is not None:
            j = find(d["t"])
            if j is not None:
                assign[d["index"]] = j
    before = old[idx[0] - 1]["t"] if idx[0] > 0 else None
    after = old[idx[-1] + 1]["t"] if idx[-1] + 1 < n else None
    lo_t = (before + 2.0) if before is not None else max(0.0, (prev.get("batting_start") or 0.0) - 2.0)
    hi_t = (after - 2.0) if after is not None else prev["duration"]
    sub = [dels[i] for i in idx]
    sub_pins = {k: pins[i] for k, i in enumerate(idx) if i in pins}
    sub_assign, _ = _align(sub, cands, lo_t, hi_t, g_ball, g_over, sub_pins)
    for k, j in sub_assign.items():
        assign[idx[k]] = j
    times = interpolate_times(dels, assign, cands, g_ball, g_over, prev["duration"])
    for d in old:
        if d["over"] != over_no:
            times[d["index"]] = d["t"]  # unchanged, even if they were interpolated
    result = {**prev, "created": datetime.now().isoformat(timespec="seconds"), "candidates": len(cands),
              "pins": {str(k): v for k, v in pins.items()}, "realigned_over": over_no}
    result["deliveries"] = [old[i] if dels[i]["over"] != over_no else _entry(dels[i], i, times, assign, cands, ts, pins, g_ball, g_over, dels)
                            for i in range(n)]
    result["stats"] = stats(result["deliveries"], {d["index"]: 1 for d in result["deliveries"] if d.get("candidate") is not None})
    _summary(result, dels, times)
    return result


# Confidence rules (see confidence()).
CONF_BOTH = 0.55        # audio and motion score both at least this: a sound AND a still-then-move
CONF_GAP_FIT = 0.4      # |log(actual gap / expected gap)| to a matched neighbour under this = gap fits
CONF_RIVAL_HIGH = 0.85  # a rival sound within 4 s weaker than this share of ours → no doubt
CONF_RIVAL_MED = 0.8
CONF_MIN_STRENGTH = 0.5
RIVAL_WINDOW = 4.0
MIN_MATCHED, MIN_MINE_MATCHED = 0.4, 0.5   # below these shares of matched balls the sync is reported as failed


def interpolate_times(dels, assign, cands, g_ball, g_over, duration) -> list:
    """Matched deliveries take their candidate's time; the others are placed between their matched neighbours
    in proportion to the expected gaps (or extrapolated from the nearest one)."""
    n = len(dels)
    times = [None] * n
    for i, j in assign.items():
        times[i] = cands[j]["t"]
    matched = sorted(assign)
    if not matched:
        return times
    for i in range(n):
        if times[i] is not None:
            continue
        prev = max([k for k in matched if k < i], default=None)
        nxt = min([k for k in matched if k > i], default=None)
        if prev is not None and nxt is not None:
            mu_all = _expected_gap(dels, prev, nxt, g_ball, g_over)
            frac = _expected_gap(dels, prev, i, g_ball, g_over) / mu_all
            times[i] = times[prev] + frac * (times[nxt] - times[prev])
        elif prev is not None:
            times[i] = times[prev] + _expected_gap(dels, prev, i, g_ball, g_over)
        else:
            times[i] = times[nxt] - _expected_gap(dels, i, nxt, g_ball, g_over)
        times[i] = float(np.clip(times[i], 0, duration))
    return times


def confidence(dels, i, assign, cands, ts, g_ball, g_over) -> tuple[str, str]:
    """(high|med|low, reason) for a matched delivery: is the sound clear, does the gap to its neighbours fit,
    and is there a rival sound nearby that could be the real hit?"""
    d, j = dels[i], assign[i]
    s = cand_strength(cands[j], d["facer"])
    t = cands[j]["t"]
    near = (np.abs(ts - t) < RIVAL_WINDOW) & (np.abs(ts - t) > 0.05)
    rival = max((cand_strength(cands[k], d["facer"]) for k in np.where(near)[0]), default=0.0)
    fits = []
    for k in (i - 1, i + 1):
        if k in assign:
            lo, hi = min(i, k), max(i, k)
            mu = _expected_gap(dels, lo, hi, g_ball, g_over)
            fits.append(abs(math.log(abs(cands[assign[hi]]["t"] - cands[assign[lo]]["t"]) / mu)))
    gap_ok = bool(fits) and min(fits) < CONF_GAP_FIT
    both = cands[j].get("audio", 1) >= CONF_BOTH and cands[j].get("motion", 1) >= CONF_BOTH
    if both and gap_ok and rival < CONF_RIVAL_HIGH * s:
        return "high", ""
    if s >= CONF_MIN_STRENGTH and (gap_ok or rival < CONF_RIVAL_MED * s):
        return "med", "rival" if rival >= CONF_RIVAL_HIGH * s else ""
    return "low", "weak"


def stats(deliveries: list[dict], assign: dict) -> dict:
    mine = [e for e in deliveries if e["facer"] == "me"]
    return {"deliveries": len(deliveries), "matched": len(assign), "mine": len(mine),
            "mine_matched": sum(1 for e in mine if e["candidate"] is not None),
            "high": sum(1 for e in mine if e["conf"] == "high"), "med": sum(1 for e in mine if e["conf"] == "med"),
            "low": sum(1 for e in mine if e["conf"] == "low")}


def no_batting(duration: float) -> dict:
    """2.1: a sync without batting (a bowling + fielding reel): no balls to line up, nothing to fail."""
    return {"version": 1, "created": datetime.now().isoformat(timespec="seconds"), "batting_start": None, "duration": duration,
            "candidates": 0, "ok": True, "error": None, "deliveries": [], "gap_ball": PRIORS["gap_ball"], "gap_over_extra": 0,
            "auto_start": None, "batting": False,
            "stats": {"deliveries": 0, "matched": 0, "mine": 0, "mine_matched": 0, "high": 0, "med": 0, "low": 0}}


def spaced_evenly(sc: dict, start: float, end: float) -> dict:
    """Fallback when audio sync fails: spread the deliveries evenly, all marked needs check."""
    dels = deliveries_from_scorecard(sc)
    n = len(dels)
    step = (end - start) / max(1, n)
    out = [{**d, "index": i, "t": round(start + step * (i + 0.5), 3), "candidate": None, "strength": None, "conf": "low", "why": "even",
            "kind": parse_code(d["code"])["kind"], "label": parse_code(d["code"])["label"]} for i, d in enumerate(dels)]
    mine = [e for e in out if e["facer"] == "me"]
    return {"version": 1, "created": datetime.now().isoformat(timespec="seconds"), "batting_start": start, "duration": end,
            "candidates": 0, "ok": True, "error": None, "deliveries": out, "gap_ball": round(step, 1), "gap_over_extra": 0,
            "auto_start": start, "even": True,
            "stats": {"deliveries": n, "matched": 0, "mine": len(mine), "mine_matched": 0, "high": 0, "med": 0, "low": len(mine)}}
