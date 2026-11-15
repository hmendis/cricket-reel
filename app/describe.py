"""E2: social media descriptions for each exported file - Meta (Instagram + Facebook Reels), TikTok and
YouTube Shorts - written by Claude with the rules of your indoor-cricket-socials skill.

Each file (the reel and every exported clip) has its own prompt: what you want to say about it. The match facts
for that file are added automatically, so Claude never has to guess a score or a result. The texts are kept in
match.json and written to exports/<match>_descriptions.txt next to the videos, rewritten on every Generate.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field

from . import config, matches, usage

# The indoor-cricket-socials skill, as rules for the model, in parts you can edit in Settings (config.DESCRIBE_PROMPTS).
def prompts() -> dict:
    s = config.load_settings()
    p = {**config.DESCRIBE_PROMPTS, **(s.get("describe_prompts") or {})}
    venue = s.get("venue") or "the indoor cricket centre"
    return {k: v.replace("{venue}", venue) if k != "user" else v for k, v in p.items()}


def system_prompt() -> str:
    p = prompts()
    return (p["shared"] + "\n\nWrite one description per platform group, tuned to how that audience behaves:\n"
            + "\n".join(f"- {p[k]}" for k in ("meta", "tiktok", "yt_title", "yt_desc")))





class Descriptions(BaseModel):
    meta: str = Field(description="Instagram + Facebook Reels caption, 25-35 words")
    tiktok: str = Field(description="TikTok caption, 10-20 words")
    youtube_title: str = Field(description="YouTube Shorts title, at most 50 characters")
    youtube_description: str = Field(description="YouTube Shorts description, 20-30 words")


class DescribeError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _schema() -> dict:
    s = Descriptions.model_json_schema()
    s["additionalProperties"] = False
    s["required"] = list(s["properties"])
    for p in s["properties"].values():
        p.pop("title", None)
    s.pop("title", None)
    return s


HIGHLIGHT = {"batting": "batting", "bowlfield": "bowling and fielding", "allround": "all-round (batting, bowling and fielding)"}


def _figures(m: dict, sc: dict | None) -> dict:
    """Everything the descriptions may say about the match, from the score sheet only."""
    out = {"us": "", "them": "", "tu": None, "tt": None, "result": "", "runs": None, "balls": None, "partner": "",
           "bowl": None, "wickets": [], "catches": len(m.get("my_catches") or [])}
    if not sc:
        return out
    mm = sc.get("match") or {}
    out.update(us=mm.get("team_us") or "", them=mm.get("team_them") or "", tu=mm.get("total_us"), tt=mm.get("total_them"),
               result=mm.get("result") or "")
    from .scorecard import validate
    v = validate(sc)
    out.update(runs=v["batter"]["calc_runs"], balls=v["batter"]["calc_balls"], partner=(sc.get("partner") or {}).get("name", ""))
    if v.get("innings"):
        out["bowl"] = v["innings"]["bowling"]
        out["wickets"] = v["innings"]["wickets"]
    return out


def _how_counts(ws: list[dict]) -> str:
    n = {}
    for w in ws:
        n[w["how"]] = n.get(w["how"], 0) + 1
    return ", ".join(f"{k} {v}" for k, v in n.items())


def _kinds_of(m: dict, file: dict, clips: dict) -> list[str]:
    if file.get("kind") == "reel":
        return list(matches.REEL_TYPES.get(file.get("rtype") or m.get("reel_active") or "batting", ["batting"]))
    c = clips.get(file.get("index"))
    if not c:
        return ["batting"]
    from .reel import section_of
    return [section_of(c)]


def facts(m: dict, sc: dict | None, file: dict) -> list[str]:
    """Plain facts for one exported file, from the scorecard and the clip. Nothing else is given to Claude."""
    out, f = [], _figures(m, sc)
    s = config.load_settings()
    clips = matches.clips_by_index(m)
    kinds = _kinds_of(m, file, clips)
    hl = HIGHLIGHT.get(file.get("rtype"), "") if file.get("kind") == "reel" else kinds[0]
    out.append(f"Highlight: {hl or 'batting'} · POV from a head camera worn by the player")
    out.append(f"Venue: {s.get('venue') or 'the indoor cricket centre'} · eight-a-side indoor cricket, 16 overs a side")
    if f["us"] and f["them"] and f["tu"] is not None and f["tt"] is not None:
        out.append(f"{f['us']} {f['tu']} v {f['them']} {f['tt']}")
    if f["result"]:
        out.append(f["result"])
    if "batting" in kinds and f["runs"] is not None:
        out.append(f"The player batted: {f['runs']} off {f['balls']} balls" + (f" with {f['partner']}" if f["partner"] else ""))
    if "bowling" in kinds and f["bowl"]:
        b = f["bowl"]
        mine = [w for w in f["wickets"] if w["role"] == "bowling"]
        out.append(f"The player bowled overs {', '.join(map(str, b['overs']))}: {b['wkts']} for {b['runs']}"
                   + (f" ({', '.join(w['how'] + ' in over ' + str(w['over']) for w in mine)})" if mine else ""))
    if "fielding" in kinds and f["wickets"]:
        out.append(f"The team took {len(f['wickets'])} wickets in the field: {_how_counts(f['wickets'])}")
        if f["catches"]:
            out.append(f"The player took {f['catches']} of the catches")
    if file.get("kind") == "clip" and file.get("index") in clips:
        c = clips[file["index"]]
        if c.get("wid"):
            out.append(f"This clip: their innings, over {c['over']}, ball {c['ball']}: {c.get('batter') or 'the batter'} "
                       f"{c['label'].split('·')[-1].strip().lower()}" + (f", bowled by {c['bowler']}" if c.get("bowler") else "")
                       + (" (the player bowled it)" if c.get("role") == "bowling" else "") + (" (the player took the catch)" if c.get("my_catch") else ""))
        elif c.get("source") == "manual":
            out.append(f"This clip: {(c.get('label') or 'a moment').lower()}, while the team was {'fielding' if c.get('phase') == 'fielding' else 'batting'}")
        else:
            out.append(f"This clip: our innings, over {c['over']}, ball {c['ball']}, result {c['label']}")
    elif file.get("kind") == "reel":
        from . import reel as reel_mod
        r = reel_mod.of(m, file.get("rtype"))
        moments = [clips[e["index"]]["label"] for e in r["entries"] if e["index"] in clips]
        out.append(f"This is the {hl or 'batting'} highlight reel, {len(moments)} clips")
        if moments:
            out.append("Moments in it, in order: " + ", ".join(x or "moment" for x in moments))
    return out


def draft(m: dict, sc: dict | None, file: dict) -> str:
    """A first draft of 'what I want to say', in the player's words, so the box isn't empty."""
    f = _figures(m, sc)
    clips = matches.clips_by_index(m)
    kinds = _kinds_of(m, file, clips)
    parts = []
    if f["tu"] is not None and f["tt"] is not None and f["them"]:
        won = f["tu"] > f["tt"]
        margin = abs(f["tu"] - f["tt"])
        word = "We won" if won else "We lost" if f["tu"] < f["tt"] else "We tied"
        parts.append(f"{word}{f' by {margin} runs' if margin else ''} against {f['them']}, {f['tu']} to {f['tt']}.")
    c = clips.get(file.get("index")) if file.get("kind") == "clip" else None
    if c and c.get("wid"):
        how = c["label"].split("·")[-1].strip().lower()
        if c.get("role") == "bowling":
            parts.insert(0, f"Over {c['over']}, ball {c['ball']}: {c.get('batter') or 'the batter'} {how} off my bowling.")
        else:
            catch = " - my catch" if c.get("my_catch") else ""
            by = f" off {c['bowler']}" if c.get("bowler") else ""
            parts.insert(0, f"Over {c['over']}, ball {c['ball']}: {c.get('batter') or 'the batter'} {how}{catch}{by}.")
    elif c and c.get("source") == "manual":
        parts.insert(0, f"{(c.get('label') or 'A moment').capitalize()} while we were {'fielding' if c.get('phase') == 'fielding' else 'batting'}.")
    elif c:
        parts.insert(0, f"Over {c['over']}, ball {c['ball']}: {c['label'].lower()}. I finished {f['runs']} off {f['balls']}.")
    else:
        if "batting" in kinds and f["runs"] is not None:
            parts.append(f"I made {f['runs']} off {f['balls']}" + (f" with {f['partner'].split(' ')[0]}." if f["partner"] else "."))
        if "bowling" in kinds and f["bowl"]:
            parts.append(f"I took {f['bowl']['wkts']} for {f['bowl']['runs']} off {len(f['bowl']['overs'])} overs.")
        if "fielding" in kinds and f["wickets"]:
            parts.append(f"The team took {len(f['wickets'])} wickets in the field" + (f" and I took {'one' if f['catches'] == 1 else f['catches']} of the catches." if f["catches"] else "."))
    return " ".join(parts)


def checks(d: dict) -> dict:
    """The skill's hard rules, checked on the answer (shown next to each text)."""
    texts = [d["meta"], d["tiktok"], d["youtube_description"]]
    words = lambda s: len(s.split())  # noqa: E731
    return {
        "keyword": all("indoor cricket" in t[:125].lower() for t in texts),
        "no_hashtags": not any("#" in t for t in texts + [d["youtube_title"]]),
        "no_call_to_action": not any(re.search(r"\?|\b(comment|follow|subscribe|share|like)\b", t, re.I) for t in texts),
        "title_length": len(d["youtube_title"]) <= 50,
        "lengths": {"meta": words(d["meta"]), "tiktok": words(d["tiktok"]), "youtube_title": len(d["youtube_title"]),
                    "youtube_description": words(d["youtube_description"])},
    }


def write_one(prompt: str, fact_lines: list[str], model: str, api_key: str, client=None):
    """One Claude call: (Descriptions dict, the model that answered, response usage)."""
    import anthropic
    client = client or anthropic.Anthropic(api_key=api_key)
    tpl = prompts()["user"]
    user = (tpl.replace("{facts}", "\n".join(f"- {f}" for f in fact_lines))
            .replace("{prompt}", prompt.strip() or "(nothing extra - use the facts)"))
    request = dict(model=model, max_tokens=4000, system=system_prompt(), messages=[{"role": "user", "content": user}],
                   output_config={"effort": "low", "format": {"type": "json_schema", "schema": _schema()}})
    fallback = dict(extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"}, extra_body={"fallbacks": "default"})
    try:
        try:
            resp = client.messages.create(**request, **fallback)
        except anthropic.BadRequestError as e:
            if "fallback" not in str(e).lower():
                raise
            resp = client.messages.create(**request)
    except anthropic.AuthenticationError as e:
        raise DescribeError("The Claude API key was rejected. Check the key in Settings.") from e
    except anthropic.RateLimitError as e:
        raise DescribeError("The Claude API is rate limiting requests. Wait a minute and try again.") from e
    except anthropic.APIConnectionError as e:
        raise DescribeError("Couldn't reach the Claude API. Check the internet connection.") from e
    except anthropic.APIStatusError as e:
        raise DescribeError(f"Claude API error ({e.status_code}). Try again shortly.") from e
    used = getattr(resp, "usage", None)
    if resp.stop_reason == "refusal":
        raise DescribeError("Claude declined to write this one. Change the prompt and try again.")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        d = Descriptions.model_validate_json(text).model_dump()
    except Exception as e:  # noqa: BLE001
        raise DescribeError("Claude's answer didn't come back in the expected form. Try again.") from e
    return d, getattr(resp, "model", model), used


def descriptions_file(m: dict, sc: dict | None) -> str:
    from .export import match_slug
    return f"{match_slug(m, sc)}_descriptions.txt"


def render_text(m: dict, sc: dict | None) -> str:
    """The archive text file: one section per exported file, every platform labelled."""
    lines = [f"Descriptions for {m.get('name', '')}", ""]
    for name, d in (m.get("descriptions") or {}).items():
        t = d["text"]
        lines += [f"=== {name} ===", f"Prompt: {d.get('prompt', '')}", "",
                  "Instagram + Facebook", t["meta"], "", "TikTok", t["tiktok"], "",
                  "YouTube Shorts title", t["youtube_title"], "", "YouTube Shorts description", t["youtube_description"], "", ""]
    return "\n".join(lines)


def run(job, match_id: str, files: list[dict], model: str, api_key: str, client=None) -> dict:
    """Generate for each {name, kind, index?, prompt}; save to match.json and the text file. A job."""
    d = matches.match_dir(match_id)
    sc = config.read_json(d / "scorecard.json")
    done = {}
    for k, f in enumerate(files):
        job.update(step=0, detail=f"{k + 1} of {len(files)}: {f['name']}", progress=k / len(files))
        if f.get("kind") == "reel" and not f.get("rtype"):
            f["rtype"] = next((it.get("rtype") for e in matches.load(match_id).get("exports") or [] for it in e.get("items") or []
                               if it["name"] == f["name"]), None)
        if job.cancel.is_set():
            break
        m = matches.load(match_id)
        fl = facts(m, sc, f)
        text, served, used = write_one(f.get("prompt", ""), fl, model, api_key, client)
        usage.record(match_id, "describe", served, used or {})
        entry = {"kind": f.get("kind"), "index": f.get("index"), "prompt": f.get("prompt", ""), "facts": fl,
                 "text": text, "checks": checks(text), "model": served}
        with matches.edit(match_id) as m:
            m.setdefault("descriptions", {})[f["name"]] = entry
            matches.advance(m, "described")
        done[f["name"]] = entry
    m = matches.load(match_id)
    out = d / "exports" / descriptions_file(m, sc)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part")
    tmp.write_text(render_text(m, sc), encoding="utf-8")
    config.replace_with_retry(tmp, out)
    return {"descriptions": done, "file": str(out), "name": out.name}


def overview(match_id: str) -> dict:
    """What the Describe screen needs: the exported files, saved prompts and texts, and the cost estimate."""
    d = matches.match_dir(match_id)
    m = matches.load(match_id)
    sc = config.read_json(d / "scorecard.json")
    exported = []
    for e in reversed(m.get("exports") or []):
        for name in e.get("files", []):
            if name not in exported and (d / "exports" / name).exists():
                exported.append(name)
    clips = matches.clips_by_index(m)
    items = {it["name"]: it for e in m.get("exports") or [] for it in e.get("items") or []}  # 2.1 exports say what each file is
    files = []
    for name in exported:
        it = items.get(name)
        if it:
            f = {"name": name, "kind": it["kind"], "index": it.get("index"), "rtype": it.get("rtype")}
        else:
            kind = "reel" if name.endswith("_reel.mp4") else "clip"
            idx = None
            if kind == "clip":
                mt = re.match(r"over(\d+)_ball(\d+)_", name)
                if mt:
                    idx = next((c["index"] for c in clips.values() if c["over"] == int(mt.group(1)) and c["ball"] == int(mt.group(2))), None)
            f = {"name": name, "kind": kind, "index": idx, "rtype": "batting" if kind == "reel" else None}
        f["facts"] = facts(m, sc, f)
        f["draft"] = draft(m, sc, f)
        f["saved"] = (m.get("descriptions") or {}).get(name)
        files.append(f)
    model = config.load_settings()["model"]
    txt = d / "exports" / descriptions_file(m, sc)
    return {"files": files, "model": model, "estimate_each": usage.estimate("describe", model),
            "text_file": txt.name if txt.exists() else None, "usage": usage.summary(m), "quick_links": config.load_settings()["quick_links"]}
