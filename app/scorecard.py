"""Scorecard data model, scorer's-code parsing and the totals check.

Token rules come from config/tokens.json so codes, the wicket penalty and big-shot threshold can be
changed without touching code.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from . import config

SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")


# ---------- Data model (also the JSON schema Claude must fill in) ----------
class MatchInfo(BaseModel):
    team_us: str = Field(description="Name of the user's team (the team the named batter plays for)")
    team_them: str = Field(description="Opposition team name")
    total_us: Optional[int] = Field(description="Our team's innings total as written on the sheet, or null")
    total_them: Optional[int] = Field(description="Opposition innings total as written, or null")
    result: str = Field(description="Result as written or obvious from totals, e.g. 'X won by 24 runs'; empty if unknown")
    player_of_match: str = Field(description="Player of the match if written, else empty")
    date: str = Field(description="Match date as YYYY-MM-DD if shown, else empty")


class BatterInfo(BaseModel):
    name: str = Field(description="Batter name exactly as written on the sheet")
    runs_sheet: Optional[int] = Field(description="That batter's runs total as written on the sheet, or null")
    balls_sheet: Optional[int] = Field(description="Balls faced as written on the sheet, or null")


class Ball(BaseModel):
    facer: Literal["me", "partner"] = Field(description="'me' if written in the named batter's row, 'partner' if in the partner's row")
    code: str = Field(description="Scorer's code exactly as written, including superscripts, e.g. '4', '0', 'c', 'nb²'")
    unsure: bool = Field(description="true if the handwriting is ambiguous or the cell is hard to read")
    note: str = Field(description="If unsure: what else it could be, e.g. 'could be 5'. Otherwise empty")


class Over(BaseModel):
    number: int = Field(description="Over number")
    bowler: str = Field(description="Bowler name for this over, empty if not written")
    total_sheet: Optional[int] = Field(description="Over total as written on the sheet, or null")
    balls: list[Ball] = Field(description="Every delivery of the over, left to right in the order bowled")


class InningsBall(BaseModel):
    batter: str = Field(description="Name of the batter who faced this ball, as written")
    code: str = Field(description="Scorer's code exactly as written, including superscripts")


class InningsOver(BaseModel):
    number: int = Field(description="Over number, 1-16")
    bowler: str = Field(description="Bowler name for this over, empty if not written")
    wkts: Optional[int] = Field(description="Wickets in this over as written in the over footer (the number before the slash), or null")
    runs: Optional[int] = Field(description="Runs in this over as written in the over footer (the number after the slash), or null")
    balls: list[InningsBall] = Field(description="Every delivery of the over, left to right in the order bowled")


class Innings(BaseModel):
    """One whole innings: all 16 overs, every ball. 'batting' is our innings, 'fielding' is theirs."""
    side: Literal["batting", "fielding"] = Field(description="'batting' for the named batter's team, 'fielding' for the opposition's innings")
    team: str = Field(description="Name of the batting team in this innings")
    total: Optional[int] = Field(description="Innings total as written, or null")
    batted_first: bool = Field(description="true if this innings was batted first")
    overs: list[InningsOver] = Field(description="All overs of the innings in order")


class BowlingRow(BaseModel):
    name: str = Field(description="Player name in our team's bowling/summary table")
    overs: Optional[int] = Field(description="Overs bowled (OB), or null")
    runs: Optional[int] = Field(description="Runs conceded (RC), or null")
    wkts: Optional[int] = Field(description="Wickets (Wkts), or null")


class SheetRead(BaseModel):
    match: MatchInfo
    batter: BatterInfo
    partner: BatterInfo
    overs: list[Over] = Field(description="Only the overs the named batter's pair batted, in order")
    notes: str = Field(description="Anything the user should double-check; empty if nothing")
    # 2.1: both innings and our bowling table. Empty for sheets read by 2.0 (batting only).
    innings: list[Innings] = Field(default_factory=list, description="Both innings in full, the one batted first first; empty if they can't be read")
    bowling: list[BowlingRow] = Field(default_factory=list, description="Our team's bowling table (OB, RC, Wkts per player); empty if not on the sheet")


class Scorecard(SheetRead):
    version: int = 2
    model: str = ""
    read_at: str = ""
    continued_with_errors: bool = False


# ---------- Token rules ----------
def load_tokens() -> dict:
    return config.read_json(config.TOKENS_FILE, {})


def parse_code(code: str, tokens: dict | None = None) -> dict:
    """Return {'kind','team','bat','ball','big','label','valid'} for one scorer's code."""
    t = tokens or load_tokens()
    c = (code or "").strip().lower().translate(SUPERSCRIPTS).replace(" ", "")
    rmin, rmax = t.get("runs", {}).get("min", 0), t.get("runs", {}).get("max", 7)
    if re.fullmatch(r"\d+", c) and rmin <= int(c) <= rmax:
        n = int(c)
        big = n >= t.get("big_shot_min_runs", 4)
        return {"kind": "big" if big else "runs", "team": n, "bat": n, "ball": True, "big": big,
                "label": f"BIG SHOT · {n}" if big else ("DOT" if n == 0 else f"{n} RUN{'S' if n > 1 else ''}"), "valid": True}
    m = re.fullmatch(r"([a-z]+)(\d*)", c)
    if m:
        word, num = m.group(1), int(m.group(2) or 0)
        extras = t.get("extras", {})
        if word in extras:
            e = extras[word]
            team = e.get("team_runs", 0) + num
            bat = team if t.get("batter_total_includes_extras", True) else 0
            return {"kind": "extra", "team": team, "bat": bat, "ball": bool(e.get("counts_as_ball")), "big": False,
                    "label": e.get("label", word).upper(), "valid": True}
        dismissals = t.get("dismissals", {})
        if word in dismissals:
            pen = t.get("wicket_penalty", -5)
            return {"kind": "wicket", "team": pen, "bat": pen, "ball": True, "big": False,
                    "label": f"WICKET · {dismissals[word].upper()}", "valid": True}
    return {"kind": "invalid", "team": 0, "bat": 0, "ball": False, "big": False, "label": "?", "valid": False}


# ---------- Names ----------
def norm_name(name: str) -> str:
    return re.sub(r"[^a-z ]", "", (name or "").lower()).strip()


def same_player(a: str, b: str) -> bool:
    """Sheets write names inconsistently ("Alex Carter" / "alex carter"); compare letters only."""
    return bool(norm_name(a)) and norm_name(a) == norm_name(b)


def innings_of(sc, side: str):
    return next((i for i in (sc.innings or []) if i.side == side), None)


def _side_word(side: str) -> str:
    return "Their" if side == "fielding" else "Our"


def wickets(sc, tokens: dict | None = None) -> list[dict]:
    """Every wicket our team took (their innings), in order. A wicket is 'bowling' when the over's bowler is me
    (the sheet has no fielder names), otherwise 'fielding'."""
    if isinstance(sc, dict):
        sc = Scorecard.model_validate(sc)
    t = tokens or load_tokens()
    inn = innings_of(sc, "fielding")
    out = []
    if not inn:
        return out
    dismissals = t.get("dismissals", {})
    for o in inn.overs:
        for bi, b in enumerate(o.balls):
            if parse_code(b.code, t)["kind"] != "wicket":
                continue
            word = re.match(r"[a-z]+", b.code.strip().lower()).group()
            mine = same_player(o.bowler, sc.batter.name)
            out.append({"id": f"{o.number}.{bi + 1}", "over": o.number, "ball": bi + 1, "balls_in_over": len(o.balls),
                        "code": b.code, "how": dismissals.get(word, word).lower(), "batter": b.batter, "bowler": o.bowler,
                        "role": "bowling" if mine else "fielding"})
    return out


def validate_innings(sc, tokens: dict | None = None) -> dict | None:
    """Both-innings checks (2.1): the wicket codes in each over match its footer, the footers add up to the innings
    total, and my bowling figures match the bowling table. None for a batting-only (2.0) scorecard."""
    if not sc.innings:
        return None
    t = tokens or load_tokens()
    out, errors = {"innings": []}, []
    for inn in sc.innings:
        overs, runs = [], 0
        for o in inn.overs:
            w = sum(parse_code(b.code, t)["kind"] == "wicket" for b in o.balls)
            ok = o.wkts is None or o.wkts == w
            overs.append({"number": o.number, "bowler": o.bowler, "wkts_codes": w, "wkts_sheet": o.wkts, "runs_sheet": o.runs, "ok": ok})
            if not ok:
                errors.append(f"{_side_word(inn.side)} innings over {o.number}: the codes show {w} wicket(s), the footer says {o.wkts}")
            runs += o.runs or 0
        sum_ok = inn.total is None or any(o.runs is None for o in inn.overs) or runs == inn.total
        if not sum_ok:
            errors.append(f"{_side_word(inn.side)} innings: the over footers add up to {runs}, the total is {inn.total}")
        out["innings"].append({"side": inn.side, "team": inn.team, "total": inn.total, "footer_sum": runs, "sum_ok": sum_ok,
                               "overs": overs, "overs_ok": sum(o["ok"] for o in overs), "batted_first": inn.batted_first})
    me = sc.batter.name
    field = innings_of(sc, "fielding")
    mine = [o for o in (field.overs if field else []) if same_player(o.bowler, me)]
    ws = wickets(sc, t)
    fig = {"overs": [o.number for o in mine], "runs": sum(o.runs or 0 for o in mine),
           "wkts": sum(1 for w in ws if w["role"] == "bowling")}
    row = next((r for r in sc.bowling if same_player(r.name, me)), None)
    fig["table"] = row.model_dump() if row else None
    fig["ok"] = row is None or ((row.overs is None or row.overs == len(mine)) and (row.runs is None or row.runs == fig["runs"])
                                and (row.wkts is None or row.wkts == fig["wkts"]))
    if not fig["ok"]:
        errors.append(f"Your bowling adds up to {fig['wkts']}/{fig['runs']} off {len(mine)} overs; the bowling table says "
                      f"{row.wkts}/{row.runs} off {row.overs}")
    out.update({"bowling": fig, "wickets": ws, "errors": errors, "ok": not errors})
    return out


# ---------- Totals check ----------
def validate(sc: Scorecard | dict, tokens: dict | None = None) -> dict:
    if isinstance(sc, dict):
        sc = Scorecard.model_validate(sc)
    t = tokens or load_tokens()
    bpo = t.get("balls_per_over", 6)
    cells, overs_out, errors, warnings = [], [], [], []
    tot = {"me": [0, 0], "partner": [0, 0]}
    unsure = 0
    for oi, over in enumerate(sc.overs):
        calc, legal = 0, 0
        for bi, b in enumerate(over.balls):
            p = parse_code(b.code, t)
            if b.unsure:
                unsure += 1
            if not p["valid"]:
                cells.append({"over": oi, "ball": bi, "error": f"'{b.code}' isn't a known code"})
                continue
            calc += p["team"]
            tot[b.facer][0] += p["bat"]
            if p["ball"]:
                legal += 1
                tot[b.facer][1] += 1
        ok = over.total_sheet is None or over.total_sheet == calc
        ow = []
        if legal < bpo:
            ow.append(f"only {legal} deliveries (expected {bpo})")
        if over.total_sheet is None:
            ow.append("No over total on the sheet to check against")
        overs_out.append({"number": over.number, "calc": calc, "sheet": over.total_sheet, "ok": ok, "legal_balls": legal, "warnings": ow})
        if not ok:
            errors.append(f"Over {over.number}: balls add to {calc}, sheet says {over.total_sheet}")
        warnings += [f"Over {over.number}: {w}" for w in ow]

    def bat(info, key):
        r, n = tot[key]
        ok = (info.runs_sheet is None or info.runs_sheet == r) and (info.balls_sheet is None or info.balls_sheet == n)
        return {"name": info.name, "calc_runs": r, "calc_balls": n, "sheet_runs": info.runs_sheet, "sheet_balls": info.balls_sheet, "ok": ok}

    me, pa = bat(sc.batter, "me"), bat(sc.partner, "partner")
    for b in (me, pa):
        if not b["ok"]:
            errors.append(f"{b['name']}: balls add to {b['calc_runs']} ({b['calc_balls']}), sheet says {b['sheet_runs']} ({b['sheet_balls']})")
    if cells:
        errors.insert(0, f"{len(cells)} cell(s) contain an unknown code")
    if not sc.overs:
        errors.append("No overs found for your pair")
    both = validate_innings(sc, t)
    if both:
        errors += both["errors"]
    return {"ok": not errors, "overs": overs_out, "batter": me, "partner": pa, "cells": cells,
            "unsure": unsure, "errors": errors, "warnings": warnings, "innings": both}
