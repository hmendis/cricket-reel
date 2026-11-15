"""Import a score sheet from a Spawtz league page (e.g. https://<venue>.spawtz.com/Leagues/IndoorCricket/Scoresheet?FixtureId=...).

The page is a plain HTML table, so it's parsed directly - exact values, no AI needed.
"""
from __future__ import annotations

import difflib
import re
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser

from .scorecard import SheetRead

SUP = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
USER_AGENT = "CricketReel/1.0 (personal highlight tool)"


class ImportError_(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# ---------- Fetch ----------
def check_url(url: str) -> str:
    url = url.strip()
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname or not p.hostname.endswith(".spawtz.com"):
        raise ImportError_("Paste a Spawtz score sheet link, e.g. https://yourcentre.spawtz.com/Leagues/IndoorCricket/Scoresheet?FixtureId=12345")
    if "scoresheet" not in p.path.lower() or "fixtureid" not in p.query.lower():
        raise ImportError_("That link isn't a score sheet page. Open the match on the venue's site, click Scoresheet and copy that address.")
    return urllib.parse.urlunparse(p._replace(scheme="https"))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """R40: follow a redirect only if it stays on a spawtz.com address."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = urllib.parse.urlparse(newurl).hostname or ""
        if not host.endswith(".spawtz.com"):
            raise ImportError_("The score sheet link redirected away from Spawtz, so it wasn't followed.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as r:
            if not (urllib.parse.urlparse(r.geturl()).hostname or "").endswith(".spawtz.com"):
                raise ImportError_("The score sheet link ended up outside Spawtz, so it wasn't read.")
            if r.status != 200:
                raise ImportError_(f"The score sheet page returned HTTP {r.status}.")
            return r.read(3_000_000).decode("utf-8", errors="replace")
    except ImportError_:
        raise
    except Exception as e:  # noqa: BLE001 - network errors come in many types
        raise ImportError_(f"Couldn't download the score sheet page ({e}). Check the internet connection and the link.") from e


# ---------- HTML → tables ----------
class _Tables(HTMLParser):
    """Collects every <table> as rows of cells: {'cls', 'colspan', 'text'}. <sup>n</sup> becomes ⁿ."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.stack, self.cell, self.in_sup, self.title, self.in_title = [], [], None, False, "", False
        self.text = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            t = {"cls": a.get("class", ""), "rows": []}
            self.tables.append(t)
            self.stack.append(t)
        elif tag == "tr" and self.stack:
            self.stack[-1]["rows"].append({"cls": a.get("class", ""), "cells": []})
        elif tag == "td" and self.stack and self.stack[-1]["rows"]:
            self.cell = {"cls": a.get("class", ""), "colspan": int(a.get("colspan", 1) or 1), "text": ""}
            self.stack[-1]["rows"][-1]["cells"].append(self.cell)
        elif tag == "sup":
            self.in_sup = True
        elif tag == "title":
            self.in_title = True

    def handle_startendtag(self, tag, attrs):
        if tag == "td":  # <td class="Blank" />
            self.handle_starttag(tag, attrs)
            self.cell = None

    def handle_endtag(self, tag):
        if tag == "table" and self.stack:
            self.stack.pop()
        elif tag == "td":
            self.cell = None
        elif tag == "sup":
            self.in_sup = False
        elif tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.cell is not None:
            self.cell["text"] += data.strip().translate(SUP) if self.in_sup else data
        self.text.append(data)


def _txt(c):
    return re.sub(r"\s+", " ", c["text"]).strip()


def _norm(name: str) -> str:
    return re.sub(r"[^a-z ]", "", name.lower()).strip()


def _int(s):
    m = re.search(r"-?\d+", s or "")
    return int(m.group()) if m else None


# ---------- Parse ----------
def parse_innings(table) -> dict:
    """One OversTable → {'team', 'pairs': [{'batters': [n1, n2], 'row_totals': [t1, t2], 'overs': [...]}]}"""
    rows = table["rows"]
    team = ""
    for r in rows:
        heads = [_txt(c) for c in r["cells"] if "TeamHeader" in c["cls"]]
        if len(heads) >= 2:
            team = heads[1]
            break
    pairs, i = [], 0
    while i < len(rows):
        r = rows[i]
        if any("OverNo" in c["cls"] for c in r["cells"]):
            overs, cells = [], r["cells"]
            for k, c in enumerate(cells):
                if "OverNo" in c["cls"]:
                    bowler = cells[k + 1]
                    overs.append({"number": _int(_txt(c)), "bowler": _txt(bowler), "cols": bowler["colspan"]})
            ball_rows = []
            j = i + 1
            while j < len(rows) and "BallRow" in rows[j]["cls"]:
                ball_rows.append(rows[j])
                j += 1
            spacer = rows[j] if j < len(rows) and "SpacerRow" in rows[j]["cls"] else None
            if len(ball_rows) == 2:
                pairs.append(_parse_pair(overs, ball_rows, spacer))
            i = j + 1
        else:
            i += 1
    return {"team": team, "pairs": pairs}


def _parse_pair(overs, ball_rows, spacer):
    names, grids, row_totals = [], [], []
    for br in ball_rows:
        cells = br["cells"]
        names.append(_txt(cells[0]))
        pos, per_over = 1, []
        for o in overs:
            per_over.append([_txt(c) for c in cells[pos:pos + o["cols"]]])
            pos += o["cols"] + 1  # skip the batter's over-total cell
        grids.append(per_over)
        row_totals.append(_int(_txt(cells[-1])))
    over_totals, over_wkts = [], []
    if spacer:
        totals = [c for c in spacer["cells"] if "TotalCell" in c["cls"]]
        for t in totals[:len(overs)]:
            m = re.match(r"\s*(\d+)\s*/\s*(-?\d+)", _txt(t))  # the footer is "wickets/runs", e.g. 2/-3
            over_totals.append(int(m.group(2)) if m else None)
            over_wkts.append(int(m.group(1)) if m else None)
    out = []
    for oi, o in enumerate(overs):
        balls = []
        for col in range(o["cols"]):
            a, b = grids[0][oi][col], grids[1][oi][col]
            if a and b:  # shouldn't happen on a valid sheet
                balls.append({"facer": 0, "code": a, "unsure": True, "note": f"Both batters have a value in this column ({a} / {b})"})
                balls.append({"facer": 1, "code": b, "unsure": True, "note": "Both batters have a value in this column"})
            elif a or b:
                balls.append({"facer": 0 if a else 1, "code": a or b, "unsure": False, "note": ""})
        out.append({"number": o["number"], "bowler": o["bowler"], "total_sheet": over_totals[oi] if oi < len(over_totals) else None,
                    "wkts_sheet": over_wkts[oi] if oi < len(over_wkts) else None, "balls": balls})
    return {"batters": names, "row_totals": row_totals, "overs": out}


def full_innings(inn: dict, side: str, total, batted_first: bool) -> dict:
    """One parsed OversTable as a whole innings (2.1): every over in order, each ball with the batter who faced it."""
    overs = []
    for p in inn["pairs"]:
        for o in p["overs"]:
            overs.append({"number": o["number"], "bowler": o["bowler"], "wkts": o.get("wkts_sheet"), "runs": o["total_sheet"],
                          "balls": [{"batter": p["batters"][b["facer"]], "code": b["code"]} for b in o["balls"]]})
    return {"side": side, "team": inn["team"], "total": total, "batted_first": batted_first, "overs": sorted(overs, key=lambda o: o["number"])}


def bowling_table(tables: list[dict], team: str) -> list[dict]:
    """The per-team summary table at the bottom of the sheet (Name, RS, SR, OB, RC, Wkts, Econ, C) as bowling rows."""
    for t in tables:
        rows = t["rows"]
        if not rows or "OversTable" not in t["cls"]:
            continue
        head = [_txt(c) for c in rows[0]["cells"] if "TeamHeader" in c["cls"]]
        cols = next(([_txt(c) for c in r["cells"]] for r in rows if any("MatchSummaryCol" in c["cls"] for c in r["cells"])), None)
        if len(head) != 1 or _norm(head[0]) != _norm(team) or not cols or "OB" not in cols:
            continue
        ix = {k: cols.index(k) for k in ("OB", "RC", "Wkts") if k in cols}
        out = []
        for r in rows:
            cells = [_txt(c) for c in r["cells"]]
            if len(cells) == len(cols) and not any("MatchSummaryCol" in c["cls"] for c in r["cells"]) and cells[0]:
                out.append({"name": cells[0], "overs": _int(cells[ix["OB"]]) if "OB" in ix else None,
                            "runs": _int(cells[ix["RC"]]) if "RC" in ix else None, "wkts": _int(cells[ix["Wkts"]]) if "Wkts" in ix else None})
        return out
    return []


def find_batter(innings: list[dict], batter: str, aliases: list[str] | None = None):
    """Return (innings, pair, index-in-pair) for the closest matching batter name. aliases (2.1): other ways the
    sheet may write my name; the best match of all of them wins."""
    best, best_score = None, 0.0
    for want in [_norm(x) for x in [batter, *(aliases or [])] if x and x.strip()]:
        for inn in innings:
            for p in inn["pairs"]:
                for k, name in enumerate(p["batters"]):
                    n = _norm(name)
                    tokens = n.split()
                    score = 1.0 if n == want else 0.95 if want and (want in tokens or want == " ".join(tokens[:len(want.split())])) \
                        else difflib.SequenceMatcher(None, want, n).ratio()
                    if score > best_score:
                        best, best_score = (inn, p, k), score
    if not best or best_score < 0.75:
        names = sorted({n for inn in innings for p in inn["pairs"] for n in p["batters"]})
        raise ImportError_(f"Couldn't find a batter called “{batter}” on this score sheet. Batters on it: {', '.join(names)}.")
    return best


def parse(html: str, batter: str, url: str = "", aliases: list[str] | None = None) -> SheetRead:
    p = _Tables()
    p.feed(html)
    overs_tables = [t for t in p.tables if "OversTable" in t["cls"]]
    if not overs_tables:
        raise ImportError_("This page doesn't contain a score sheet (no overs table found). Check the link.")
    innings = [i for i in (parse_innings(t) for t in overs_tables) if i["pairs"]]  # other OversTables are bowling summaries
    if not innings:
        raise ImportError_("Couldn't find any batting pairs on this score sheet. The match may not have been scored yet.")
    inn, pair, k = find_batter(innings, batter, aliases)
    me, partner = k, 1 - k

    # Match details: teams/date from the title, totals from the summary table, POTM from the text.
    title = re.sub(r"\s+", " ", p.title).strip()
    m = re.search(r"-\s*(.+?)\s+vs\s+(.+?)\s*\((\d{1,2})/(\d{1,2})/(\d{4})", title)
    teams = [inn2["team"] for inn2 in innings]
    date = ""
    if m:
        teams = [m.group(1).strip(), m.group(2).strip()]
        try:
            date = datetime(int(m.group(5)), int(m.group(4)), int(m.group(3))).date().isoformat()  # Australian DD/MM/YYYY
        except ValueError:
            date = ""
    us = inn["team"]
    them = next((t for t in teams if _norm(t) != _norm(us)), "")
    totals = {}
    for t in p.tables:
        if "Summary" in t["cls"].split():
            for r in t["rows"]:
                cells = [_txt(c) for c in r["cells"]]
                if len(cells) >= 6 and cells[0] and "SummaryTitle" not in r["cls"]:
                    totals[_norm(cells[0])] = _int(cells[5])
    tu, tt = totals.get(_norm(us)), totals.get(_norm(them))
    result = ""
    if tu is not None and tt is not None:
        result = f"{us} won by {tu - tt} runs" if tu > tt else f"{them} won by {tt - tu} runs" if tt > tu else "Match tied"
    pm = re.search(r"Player of the match:\s*([^()\n]+?)\s*(?:\(|$)", " ".join(p.text))
    potm = pm.group(1).strip() if pm else ""

    # 2.1: both innings in full (the first OversTable was batted first) and our bowling table
    both = []
    for k, i2 in enumerate(innings[:2]):
        ours = _norm(i2["team"]) == _norm(us)
        both.append(full_innings(i2, "batting" if ours else "fielding", tu if ours else tt, k == 0))
    overs = [{"number": o["number"], "bowler": o["bowler"], "total_sheet": o["total_sheet"],
              "balls": [{**b, "facer": "me" if b["facer"] == me else "partner"} for b in o["balls"]]} for o in pair["overs"]]
    return SheetRead.model_validate({
        "match": {"team_us": us, "team_them": them, "total_us": tu, "total_them": tt, "result": result,
                  "player_of_match": potm, "date": date},
        "batter": {"name": pair["batters"][me], "runs_sheet": pair["row_totals"][me], "balls_sheet": None},
        "partner": {"name": pair["batters"][partner], "runs_sheet": pair["row_totals"][partner], "balls_sheet": None},
        "overs": overs,
        "notes": f"Imported from the Spawtz score sheet{(' ' + url) if url else ''}.",
        "innings": both if len(both) == 2 else [],
        "bowling": bowling_table(p.tables, us),
    })


def import_url(url: str, batter: str) -> SheetRead:
    url = check_url(url)
    return parse(fetch(url), batter, url)
