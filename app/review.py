"""Clips for Review: one per ball I faced, built from sync.json and kept in match.json.

A clip remembers my edits. When the sync is re-run, clips I edited or confirmed keep my contact time;
the others take the new synced time.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from . import config, matches


WICKET_BASE, MANUAL_BASE = 1000, 2000   # 2.1: clip indexes for wickets in the field and clips added in Sync


class Clip(BaseModel):
    index: int                      # delivery index in the pair's sequence (sync.json); 1000+ wickets, 2000+ added clips
    over: int
    ball: int
    code: str
    kind: str = "runs"              # runs | big | wicket | extra | invalid
    label: str = ""                 # result badge text, e.g. "BIG SHOT · 5"
    t: float                        # contact time (s) on the match timeline
    t_sync: Optional[float] = None  # what the sync proposed
    conf: str = "low"               # sync confidence: high | med | low
    before: float = Field(1.0, ge=0.2, le=10)
    after: float = Field(2.0, ge=0.2, le=10)
    keep: bool = True
    star: bool = False
    confirmed: bool = False         # I checked it (Enter). "Needs check" = conf low and not confirmed.
    edited: bool = False            # I moved the contact point
    text: Optional[str] = None      # on-screen label override (None = default)
    auto: Optional[str] = None      # why it started as not kept ("dot ball", "leg-side wide", "no-ball"), K2
    # 2.1 (the plan calls this the clip's kind; `kind` above is already the ball result)
    role: str = "batting"           # batting | bowling | fielding | other
    source: str = "sheet"           # sheet | manual (added in Sync; re-sync never moves it)
    phase: str = "batting"          # the part of the recording it's in: batting | fielding
    wconf: Optional[str] = None     # wickets in the field: confirmed | celebration | timing
    role_set: bool = False          # I changed the role by hand; re-sync keeps it
    wid: Optional[str] = None       # wicket id on the sheet, e.g. "12.1"
    batter: str = ""                # wickets: who was out
    bowler: str = ""
    my_catch: bool = False          # a caught wicket I took (the sheet has no fielder names, so I mark them)
    t_open: Optional[float] = None  # wickets: where Review starts playing (the celebration)
    # 2.2: also export this clip on its own. None = not set by me yet: on for highlights (see export_on).
    export_clip: Optional[bool] = None

    @property
    def id(self) -> str:
        if self.source == "manual":
            return f"m{self.index}"
        return f"{'f' if self.phase == 'fielding' else 'o'}{self.over}b{self.ball}"


def is_highlight(c: dict) -> bool:
    """2.2: a wicket in the field, a big shot (4+ runs) or a starred clip. Same rule as static/js/core/reel.js."""
    code = str(c.get("code") or "").strip()
    big = c.get("source") != "manual" and not c.get("wid") and code.isdigit() and int(code) >= 4
    return bool(c.get("wid")) or big or bool(c.get("star"))


def export_on(c: dict) -> bool:
    """Does this clip export on its own? Only kept clips do: my explicit choice, else on for highlights."""
    if not c.get("keep"):
        return False
    return bool(c["export_clip"]) if c.get("export_clip") is not None else is_highlight(c)


AUTO_DROP = {"dot": "dot ball", "ls": "leg-side wide", "nb": "no-ball"}


def auto_drop_reason(code: str, rules: dict | None) -> Optional[str]:
    """K2: dots and leg-side wides (and no-balls if switched on) start as not kept. Everything else is kept."""
    c = (code or "").strip().lower()
    rules = {**{"dot": True, "ls": True, "nb": False}, **(rules or {})}
    if rules["dot"] and c == "0":
        return AUTO_DROP["dot"]
    if rules["ls"] and c.startswith("ls"):
        return AUTO_DROP["ls"]
    if rules["nb"] and c.startswith("nb"):
        return AUTO_DROP["nb"]
    return None


CONF_OF_WICKET = {"confirmed": "high", "celebration": "med", "timing": "low"}


def _keep_edits(c: Clip, prev: dict | None, same: bool) -> None:
    if not prev or not same:
        return
    for k in ("before", "after", "keep", "star", "text", "auto", "export_clip"):
        setattr(c, k, prev.get(k, getattr(c, k)))
    if prev.get("role_set"):
        c.role, c.role_set = prev.get("role", c.role), True
    if prev.get("edited"):
        c.t, c.edited = prev["t"], True


def wicket_clips(match: dict, sync: dict, old: dict) -> list[dict]:
    """One clip per wicket our team took (their innings), at the time the fielding sync placed it."""
    f = sync.get("fielding") or {}
    catches = set(match.get("my_catches") or [])
    out = []
    for k, w in enumerate(f.get("wickets") or []):
        idx = WICKET_BASE + k
        c = Clip(index=idx, over=w["over"], ball=w["ball"], code=w["code"], kind="wicket",
                 label=f"WICKET · {w['how'].upper()}", t=w["t"], t_sync=w["t"], conf=CONF_OF_WICKET.get(w["conf"], "low"),
                 before=w.get("before", 3.0), after=w.get("after", 4.0), role=w["role"], phase="fielding", wconf=w["conf"],
                 confirmed=w["conf"] == "confirmed", wid=w["id"], batter=w.get("batter", ""), bowler=w.get("bowler", ""),
                 my_catch=w["id"] in catches and w["how"] == "caught",
                 t_open=round(w["t"] + 1.5, 2) if w["conf"] != "timing" else None)
        prev = old.get(idx)
        _keep_edits(c, prev, bool(prev) and prev.get("wid") == w["id"])
        out.append(c.model_dump())
    return out


def manual_clips(match: dict, sync: dict, old: dict) -> list[dict]:
    """Clips added in Sync. Their time is theirs: re-sync never moves them."""
    f = sync.get("fielding") or {}
    out = []
    for mc in match.get("manual_clips") or []:
        idx = MANUAL_BASE + int(mc["id"][1:])
        phase = "fielding" if f and f["range"][0] <= mc["t"] < f["range"][1] else "batting"
        c = Clip(index=idx, over=0, ball=0, code="", kind="manual", label=(mc.get("label") or "").upper(), t=mc["t"], t_sync=mc["t"],
                 conf="high", before=3.0, after=3.0, role=mc.get("role", "other"), source="manual", phase=phase, confirmed=True)
        prev = old.get(idx)
        _keep_edits(c, prev, bool(prev))
        c.t = mc["t"]
        out.append(c.model_dump())
    return out


def clips_key(match: dict, sync: dict) -> str:
    """Changes when anything the clips are built from changes: the sync, the fielding phase, the clips I added,
    the catches I marked."""
    import hashlib
    import json as _json
    f = sync.get("fielding") or {}
    raw = _json.dumps([sync.get("created"), [(w["id"], w["t"], w["conf"]) for w in f.get("wickets") or []],
                       match.get("manual_clips") or [], sorted(match.get("my_catches") or [])], sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def build(match: dict, sync: dict) -> list[dict]:
    """Merge the latest sync into the clip list, keeping my edits."""
    s = config.load_settings()
    old = {c["index"]: c for c in match.get("clips") or []}
    out = []
    for d in sync.get("deliveries", []):
        if d["facer"] != "me" or d.get("t") is None:
            continue
        prev = old.get(d["index"])
        c = Clip(index=d["index"], over=d["over"], ball=d["ball"], code=d["code"], kind=d.get("kind", "runs"),
                 label=d.get("label", ""), t=d["t"], t_sync=d["t"], conf=d.get("conf", "low"),
                 before=s.get("clip_before", 1.0), after=s.get("clip_after", 2.0))
        c.auto = auto_drop_reason(d["code"], s.get("auto_drop"))
        c.keep = c.auto is None
        if prev and prev.get("code") == d["code"]:
            for k in ("before", "after", "keep", "star", "text", "auto", "export_clip"):
                setattr(c, k, prev.get(k, getattr(c, k)))
            if prev.get("role_set"):
                c.role, c.role_set = prev.get("role", c.role), True
            if prev.get("edited") or prev.get("confirmed"):
                c.t, c.edited, c.confirmed = prev["t"], prev.get("edited", False), prev.get("confirmed", False)
        out.append(c.model_dump())
    return out + wicket_clips(match, sync, old) + manual_clips(match, sync, old)


def load(match_id: str) -> dict:
    """Clips (rebuilt if the sync is newer than them) + everything the Review screen needs."""
    d = matches.match_dir(match_id)
    sync = config.read_json(d / "sync.json")
    if not sync:
        raise matches.MatchError("Run the sync first.", 400)
    with matches.edit(match_id) as m:
        key = clips_key(m, sync)
        if not m.get("clips") or m.get("clips_sync") != key:
            m["clips"] = build(m, sync)
            m["clips_sync"] = key
    state = config.read_json(d / "work" / "media.json", {}) or {}
    cands = config.read_json(d / "work" / "candidates.json", []) or []
    partner = [{"t": x["t"], "over": x["over"], "ball": x["ball"], "code": x["code"]}
               for x in sync["deliveries"] if x["facer"] != "me" and x.get("t") is not None]
    f = sync.get("fielding")
    return {"clips": m["clips"], "duration": state.get("duration"), "thumbs": state.get("thumbs"),
            "candidates": [{"t": c["t"], "s": c["s"]} for c in cands],
            "partner": partner,
            "defaults": {k: config.load_settings()[k] for k in ("clip_before", "clip_after")},
            "pins": m.get("sync_pins") or {}, "match": m,
            "fielding": {"range": f["range"], "fielded_first": f["fielded_first"]} if f else None}


def save(match_id: str, clips: list[dict]) -> list[dict]:
    valid = [Clip.model_validate(c).model_dump() for c in clips]
    for c in valid:
        if c["role"] not in matches.ROLES:
            raise matches.MatchError("A clip's kind must be batting, bowling, fielding or other.", 400)
    with matches.edit(match_id) as m:
        known = {c["index"] for c in m.get("clips") or []}
        if {c["index"] for c in valid} != known:
            raise matches.MatchError("The clip list doesn't match this match's balls. Reload the page.", 409)
        m["clips"] = valid
        # a catch marked (or unmarked) in Review is the same list Sheet check uses
        m["my_catches"] = sorted({c["wid"] for c in valid if c.get("my_catch") and c.get("wid")})
        sync = config.read_json(matches.match_dir(match_id) / "sync.json") or {}
        m["clips_sync"] = clips_key(m, sync)
        matches.advance(m, "review")
    return valid


def pins_from_fixes(match_id: str) -> dict:
    """Turn the clips I moved (or confirmed) into sync pins, so a re-sync lines everything else up around them."""
    with matches.edit(match_id) as m:
        pins = dict(m.get("sync_pins") or {})
        f = dict(m.get("fielding") or {})
        conf = dict(f.get("confirmed") or {})
        for c in m.get("clips") or []:
            if not (c.get("edited") or c.get("confirmed")):
                continue
            if c["index"] < WICKET_BASE:
                pins[str(c["index"])] = round(c["t"], 3)
            elif c.get("wid") and c.get("edited"):   # a wicket moved in Review counts as confirmed there for the fielding sync
                conf[c["wid"]] = round(c["t"], 2)
        m["sync_pins"] = pins
        if conf:
            f["confirmed"] = conf
            m["fielding"] = f
    return pins
