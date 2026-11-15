"""The highlight reel: which clips, in what order (first slot = the hook), and how it's dressed."""
from __future__ import annotations

import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field

from . import config, matches

TRANSITIONS = ("cut", "fade", "slideleft", "slideup", "zoomin")


class Entry(BaseModel):
    uid: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    index: int                                   # clip (delivery) index
    trans: Optional[Literal["cut", "fade", "slideleft", "slideup", "zoomin"]] = None  # transition INTO this clip; None = reel default


FONT_NAMES = ("Barlow Condensed", "Bebas Neue", "Oswald", "Plus Jakarta Sans")


class TextItem(BaseModel):
    """One piece of on-screen text on one clip (L3). Position is the centre, in % of the frame."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    text: str = Field("", max_length=200)
    x: float = Field(50, ge=0, le=100)
    y: float = Field(50, ge=0, le=100)
    font: Literal["Barlow Condensed", "Bebas Neue", "Oswald", "Plus Jakarta Sans"] = "Barlow Condensed"
    size: float = Field(7, ge=3, le=16)          # % of the video width
    bold: bool = True
    caps: bool = True
    shadow: bool = False
    outline: bool = False
    bg: Literal["none", "box", "pill"] = "box"
    bo: float = Field(0.55, ge=0, le=1)          # background opacity
    color: str = Field("#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    show: Literal["clip", "first3"] = "clip"     # the whole clip, or its first 3 s


SECTIONS = ("batting", "bowling", "fielding")
RTYPE_NAMES = {"batting": "Batting", "bowlfield": "Bowling + Fielding", "allround": "All-round"}
RTYPE_SLUG = {"batting": "batting", "bowlfield": "bowling-fielding", "allround": "allround"}


class HeaderText(BaseModel):
    t: str = Field("", max_length=40)
    s: str = Field("", max_length=60)


class Reel(BaseModel):
    # 2.1: which of the three reels this is; its sections in play order (All-round only since 2.2).
    rtype: Literal["batting", "bowlfield", "allround"] = "batting"
    order: list[Literal["batting", "bowling", "fielding"]] = []
    # 2.2: header cards are gone. These stay so older reels load; nothing reads them any more.
    headers: bool = True
    header_len: float = Field(1.2, ge=0.6, le=2.4)
    header_text: dict[str, HeaderText] = {}
    entries: list[Entry] = []
    target_min: float = Field(30, ge=5, le=600)
    target_max: float = Field(45, ge=5, le=600)
    trans: Literal["cut", "fade", "slideleft", "slideup", "zoomin"] = "cut"
    trans_dur: float = Field(0.25, ge=0.2, le=0.3)
    punch: bool = False
    punch_zoom: float = Field(1.12, ge=1.10, le=1.15)
    freeze: bool = False
    freeze_dur: float = Field(0.4, ge=0.3, le=0.5)
    hook_text: str = ""
    outro_text: str = ""
    labels: bool = True
    # 2.2: music left the interface; an uploaded file and these keys stay, unused (renders have no music).
    music: Optional[str] = Field(None, pattern=r"^music\.(mp3|m4a|aac|wav|ogg|flac)$")  # R38: only what the upload writes
    music_vol: int = Field(25, ge=0, le=100)
    # Text per clip index (L3). None = not set up yet: made from hook_text / outro_text / labels (older reels).
    texts: Optional[dict[str, list[TextItem]]] = None


LABEL_COLORS = {"big": "#FFB547", "wicket": "#FF5C8A"}


def default_label(c: dict) -> str:
    code = c.get("label", "")
    if c["kind"] == "manual":
        return code or "MOMENT"
    if c.get("wid"):  # a wicket in the field: "Over 12 · CAUGHT"
        return f"Over {c['over']} · {code.split('·')[-1].strip()}"
    if c["kind"] == "big" and "·" in code:
        return f"Over {c['over']} · {code.split('·')[-1].strip()} RUNS"
    if c["kind"] == "wicket":
        return f"Over {c['over']} · WICKET"
    return f"Over {c['over']} · {'DOT BALL' if code == 'DOT' else code}"


def legacy_texts(reel: dict, clips: dict[int, dict]) -> dict[int, list[dict]]:
    """Text items for a reel set up before per-clip text. The hook text sits in the upper third, centred -
    no longer pinned to the top right (L4)."""
    out: dict[int, list[dict]] = {}
    entries = [e for e in reel["entries"] if e["index"] in clips]
    for i, e in enumerate(entries):
        c, items = clips[e["index"]], []
        if i == 0 and reel.get("hook_text", "").strip():
            items.append(TextItem(id="hook", text=reel["hook_text"].strip(), y=28, size=9, show="first3").model_dump())
        last = i == len(entries) - 1
        if last and reel.get("outro_text", "").strip():
            items.append(TextItem(id="outro", text=reel["outro_text"].strip(), y=55, size=6.5, bg="box", bo=0.6).model_dump())
        elif reel.get("labels"):
            items.append(TextItem(id="label", text=(c.get("text") or "").strip() or default_label(c), y=72, size=4.5,
                                  color=LABEL_COLORS.get(c["kind"], "#FFFFFF")).model_dump())
        if items:
            out[c["index"]] = items
    return out


def texts_for(reel: dict, clips: dict[int, dict]) -> dict[int, list[dict]]:
    """The text items to draw on each clip, by clip index."""
    if reel.get("texts") is None:
        return legacy_texts(reel, clips)
    return {int(k): [TextItem.model_validate(t).model_dump() for t in v] for k, v in reel["texts"].items()}


def highlight_score(c: dict) -> float:
    """Biggest moments first: a star beats everything, then big shots by runs (a 7 before a 5), then wickets,
    then by runs (twos before singles), dots and extras last."""
    runs = int(c["code"]) if c["code"].strip().isdigit() else 0
    if c["kind"] == "big":
        base = 100 + runs
    elif c["kind"] == "wicket":
        base = 90
    elif c["kind"] == "manual":
        base = 80
    elif c["kind"] == "extra":
        base = 0
    else:
        base = runs * 10
    return (1000 if c.get("star") else 0) + base


def clip_len(c: dict) -> float:
    return c["before"] + c["after"]


# ---------- 2.1: sections ----------
def kinds_of(reel: dict) -> list[str]:
    return list(matches.REEL_TYPES.get(reel.get("rtype") or "batting", ["batting"]))


def section_of(c: dict) -> str:
    """The section a clip plays in: its kind, and an 'other' clip goes with the phase it was recorded in."""
    r = c.get("role") or "batting"
    if r == "other":
        return "fielding" if c.get("phase") == "fielding" else "batting"
    return r


def single_sequence(reel: dict) -> bool:
    """2.2: a Bowling + Fielding reel has no sections: its clips play as one sequence, by ball unless reordered."""
    return (reel.get("rtype") or "batting") == "bowlfield"


def order_of(reel: dict) -> list[str]:
    ks = kinds_of(reel)
    o = [s for s in (reel.get("order") or []) if s in ks]
    return o + [s for s in ks if s not in o]


def ordered(reel: dict, clips: dict[int, dict]) -> list[tuple[str, object]]:
    """What plays, in order: ("clip", entry). The first entry is the hook, taken out of its section; then each
    section in the reel's order (All-round), or the rest as stored (Batting, Bowling + Fielding). 2.2: no header
    cards, also for older reels saved with headers on."""
    ks = kinds_of(reel)
    entries = [e for e in reel["entries"] if e["index"] in clips and section_of(clips[e["index"]]) in ks]
    if not entries:
        return []
    if single_sequence(reel) or len(ks) == 1:
        return [("clip", e) for e in entries]
    out = [("clip", entries[0])]
    for s in order_of(reel):
        out += [("clip", e) for e in entries[1:] if section_of(clips[e["index"]]) == s]
    return out


def total_length(reel: dict, clips: dict[int, dict]) -> float:
    t = 0.0
    for i, (_, e) in enumerate(ordered(reel, clips)):
        t += clip_len(clips[e["index"]]) + (reel["freeze_dur"] if i == 0 and reel["freeze"] else 0)
        if i > 0 and (e.get("trans") or reel["trans"]) != "cut":
            t -= reel["trans_dur"]
    return round(t, 2)


def flatten_by_time(reel: dict, clips: dict[int, dict]) -> dict:
    """An older Bowling + Fielding reel kept its clips grouped by section. Play them as one sequence by ball - unless
    the owner had reordered a section by hand (a section not in time order), then their order stays."""
    if not single_sequence(reel):
        return reel
    rest = [e for e in reel["entries"][1:] if e["index"] in clips]
    for s in ("bowling", "fielding"):
        ts = [clips[e["index"]]["t"] for e in rest if section_of(clips[e["index"]]) == s]
        if ts != sorted(ts):
            return reel
    rest.sort(key=lambda e: clips[e["index"]]["t"])
    return {**reel, "entries": reel["entries"][:1] + rest}


def _pool(clips: list[dict], kinds: list[str]) -> list[dict]:
    pool = [c for c in clips if c["keep"] and section_of(c) in kinds
            and (c.get("star") or c["kind"] in ("wicket", "manual") or (c["kind"] in ("big", "runs") and c["code"].strip() != "0"))]
    return pool or [c for c in clips if c["keep"] and section_of(c) in kinds]


def default_entries_sequence(clips: list[dict], target_max: float, kinds: list[str]) -> list[dict]:
    """2.2, Bowling + Fielding: the best clip of all is the hook; the best of the rest fill the target; they play in
    ball order (time)."""
    pool = _pool(clips, kinds)
    if not pool:
        return []
    rank = sorted(pool, key=lambda c: (-highlight_score(c), c["index"]))
    hook, left, pick = rank[0], target_max - clip_len(rank[0]), []
    for c in rank[1:]:
        if clip_len(c) - 0.25 <= left:
            pick.append(c)
            left -= clip_len(c) - 0.25
    return [Entry(index=c["index"]).model_dump() for c in [hook] + sorted(pick, key=lambda c: c["t"])]


def default_entries_sections(clips: list[dict], target_max: float, kinds: list[str]) -> list[dict]:
    """Auto-fill for a reel with several sections: the best clip of all is the hook; then the sections take turns
    adding their best remaining clip (stars, wickets and added clips, then the biggest shots) until the target is
    reached, so every section gets its share. Inside a section, batting is biggest first and wickets are in match
    order."""
    pool = _pool(clips, kinds)
    if not pool:
        return []
    rank = sorted(pool, key=lambda c: (-highlight_score(c), c["index"]))
    hook = rank[0]
    left = target_max - clip_len(hook)
    cand = {s: [c for c in rank[1:] if section_of(c) == s] for s in kinds}
    pick = {s: [] for s in kinds}
    added = True
    while added:
        added = False
        for s in kinds:
            if cand[s] and clip_len(cand[s][0]) - 0.25 <= left:
                c = cand[s].pop(0)
                pick[s].append(c)
                left -= clip_len(c) - 0.25
                added = True
            elif cand[s]:
                cand[s] = []
    out = [hook]
    for s in kinds:
        out += sorted(pick[s], key=lambda c: (-highlight_score(c), c["t"]) if s == "batting" else (c["t"],))
    return [Entry(index=c["index"]).model_dump() for c in out]


def default_entries(clips: list[dict], target_max: float, kinds: list[str] | None = None) -> list[dict]:
    """Biggest moments first (the first one is the hook), ties in match order. Dots and extras stay out unless
    starred; if it's too long, the lowest-scoring clips are left out until it fits."""
    kinds = kinds or ["batting"]
    if sorted(kinds) == ["bowling", "fielding"]:
        return default_entries_sequence(clips, target_max, kinds)
    if len(kinds) > 1 or kinds != ["batting"]:
        return default_entries_sections(clips, target_max, kinds)
    pool = [c for c in clips if section_of(c) == "batting" and c["keep"] and (c.get("star") or c["kind"] == "manual" or (c["kind"] in ("big", "wicket", "runs") and c["code"].strip() != "0"))]
    if not pool:
        pool = [c for c in clips if c["keep"] and section_of(c) == "batting"]
    keep = sorted(pool, key=lambda c: (-highlight_score(c), c["index"]))
    while len(keep) > 1 and sum(clip_len(c) for c in keep) > target_max:
        drop = min((c for c in keep[1:] if not c.get("star")), key=lambda c: (highlight_score(c), -c["index"]), default=None)
        if drop is None:
            break
        keep.remove(drop)
    if not keep:
        return []
    return [Entry(index=c["index"]).model_dump() for c in keep]


def suggestions(sc: dict, clips: list[dict]) -> dict:
    """Hook text ideas and the outro, pre-filled from the scorecard."""
    m = sc["match"]
    from .scorecard import validate
    v = validate(sc)
    runs, balls = v["batter"]["calc_runs"], v["batter"]["calc_balls"]
    big = sum(1 for c in clips if c["kind"] == "big")
    them = m.get("team_them") or "them"
    hooks = [f"{runs} off {balls} vs {them}"]
    if big:
        hooks.append(f"{big} big shot{'s' if big > 1 else ''} vs {them}")
    tu, tt = m.get("total_us"), m.get("total_them")
    if tu is not None and tt is not None and tu != tt:
        hooks.append(f"{m['team_us']} beat {them} by {tu - tt}" if tu > tt else f"{runs} off {balls} in a tight one")
    outro = ""
    if tu is not None and tt is not None:
        outro = (f"{m['team_us']} {tu} def. {them} {tt}" if tu > tt else f"{them} {tt} def. {m['team_us']} {tu}" if tt > tu
                 else f"{m['team_us']} {tu} tied with {them} {tt}")
    if m.get("player_of_match"):
        outro += f"\nPlayer of the match: {m['player_of_match']}"
    return {"hooks": hooks, "outro": outro.strip()}


def _new(rtype: str, sug: dict, clips: list[dict]) -> dict:
    r = Reel(rtype=rtype, order=list(matches.REEL_TYPES[rtype]), hook_text=sug["hooks"][0] if rtype == "batting" else "",
             outro_text=sug["outro"], target_max=45 if rtype == "batting" else 60,
             target_min=30 if rtype == "batting" else 45).model_dump()
    r["entries"] = default_entries(clips, r["target_max"], kinds_of(r))
    return r


def load(match_id: str, rtype: str | None = None) -> dict:
    """One reel (the active one, or rtype) and what the Arrange screen needs. A match starts with the reel picked in
    New match; the other kinds are made on request."""
    d = matches.match_dir(match_id)
    m = matches.load(match_id)
    clips = m.get("clips") or []
    if not clips:
        raise matches.MatchError("Review your clips first.", 400)
    sc = config.read_json(d / "scorecard.json")
    sug = suggestions(sc, clips)
    rtype = rtype or m.get("reel_active") or m.get("highlights") or "batting"
    if not any(c.get("phase") == "fielding" or c.get("role") in ("bowling", "fielding") for c in clips) and not (m.get("reels") or {}).get(rtype):
        rtype = "batting"   # a batting-only sheet (or a 2.0 match): there is nothing else to make a reel of
    if rtype not in RTYPE_NAMES:
        raise matches.MatchError("No such reel.", 404)
    known = {c["index"]: c for c in clips}
    raw = (m.get("reels") or {}).get(rtype)
    if raw:
        reel = Reel.model_validate(raw).model_dump()
        reel["entries"] = [e for e in reel["entries"] if e["index"] in known]  # clips can disappear after a re-sync
        reel = flatten_by_time(reel, known)
    else:
        reel = _new(rtype, sug, clips)
        with matches.edit(match_id) as m:
            reels = dict(m.get("reels") or {})
            if reels.get(rtype):  # another request made it meanwhile
                reel = Reel.model_validate(reels[rtype]).model_dump()
            else:
                reels[rtype] = reel
                m["reels"] = reels
            m["reel_active"] = rtype
    by = known
    return {"reel": reel, "clips": clips, "suggestions": sug, "total": total_length(reel, by),
            "texts": {str(k): v for k, v in texts_for(reel, by).items()},  # what each clip shows (old reels: from hook/outro/labels)
            "duration": (config.read_json(d / "work" / "media.json", {}) or {}).get("duration"), "match": m,
            "reels": [{"rtype": k, "name": RTYPE_NAMES[k], "count": len(v.get("entries") or []),
                       "total": total_length(Reel.model_validate(v).model_dump(), by)} for k, v in (m.get("reels") or {}).items()]}


def save(match_id: str, reel: dict) -> dict:
    r = Reel.model_validate(reel).model_dump()
    if r["target_min"] > r["target_max"]:
        r["target_min"], r["target_max"] = r["target_max"], r["target_min"]
    with matches.edit(match_id) as m:
        known = {c["index"] for c in m.get("clips") or []}
        if any(e["index"] not in known for e in r["entries"]):
            raise matches.MatchError("The reel refers to a clip that no longer exists. Reload the page.", 409)
        reels = dict(m.get("reels") or {})
        reels[r["rtype"]] = r
        m["reels"] = reels
        m["reel_active"] = r["rtype"]
        matches.advance(m, "arrange")
    return {"reel": r, "total": total_length(r, matches.clips_by_index(m))}


def auto(match_id: str, rtype: str | None = None) -> dict:
    m = matches.load(match_id)
    reel = of(m, rtype)
    reel["entries"] = default_entries(m.get("clips") or [], reel["target_max"], kinds_of(reel))
    return save(match_id, reel)


def remove(match_id: str, rtype: str) -> dict:
    with matches.edit(match_id) as m:
        reels = dict(m.get("reels") or {})
        if rtype not in reels:
            raise matches.MatchError("No such reel.", 404)
        if len(reels) == 1:
            raise matches.MatchError("A match keeps at least one reel.", 400)
        reels.pop(rtype)
        m["reels"] = reels
        if m.get("reel_active") == rtype:
            m["reel_active"] = next(iter(reels))
    return {"reels": list(reels), "active": m["reel_active"]}


def all_of(m: dict) -> dict[str, dict]:
    """Every reel of the match, with defaults filled in."""
    return {k: Reel.model_validate(v).model_dump() for k, v in (m.get("reels") or {}).items()}


def of(m: dict, rtype: str | None = None) -> dict:
    """One reel's settings (the active one by default), with defaults filled in."""
    rtype = rtype or m.get("reel_active") or m.get("highlights") or "batting"
    raw = (m.get("reels") or {}).get(rtype)
    return Reel.model_validate(raw or {"rtype": rtype if rtype in RTYPE_NAMES else "batting"}).model_dump()
