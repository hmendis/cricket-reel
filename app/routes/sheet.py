"""The score sheet: photo/PDF read by Claude, Spawtz import, the checked scorecard."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool

from .. import config, matches, sheet_reader, spawtz, usage
from ..scorecard import load_tokens, Scorecard, validate
from .matches import _full

router = APIRouter()


@router.post("/api/matches/{match_id}/sheet")
async def upload_sheet(match_id: str, file: UploadFile = File(...)):
    d = matches.match_dir(match_id)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in matches.SHEET_EXT:
        raise HTTPException(400, "The score sheet must be a JPG, PNG, WEBP or PDF.")
    # Save and check the new sheet first; the old one is only removed once the new one is known to be readable.
    incoming = d / "source" / f"incoming_sheet{ext}"
    display_new = d / "work" / "sheet_display.new.jpg"
    size = await matches.save_upload(file, incoming)
    try:
        await run_in_threadpool(sheet_reader.prepare_image, incoming, display_new)
    except sheet_reader.SheetReadError:
        incoming.unlink(missing_ok=True)
        display_new.unlink(missing_ok=True)
        raise
    with matches.edit(match_id) as m:
        for old in (d / "source").glob("sheet.*"):
            old.unlink()
        dest = d / "source" / f"sheet{ext}"
        config.replace_with_retry(incoming, dest)
        config.replace_with_retry(display_new, d / "work" / "sheet_display.jpg")
        m["sheet"] = {"file": f"source/{dest.name}", "name": file.filename, "size": size}
    return m


@router.get("/api/matches/{match_id}/sheet-image")
def sheet_image(match_id: str):
    p = matches.match_dir(match_id) / "work" / "sheet_display.jpg"
    if not p.exists():
        raise HTTPException(404, "No score sheet yet")
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/api/matches/{match_id}/read-sheet")
def read_sheet(match_id: str):
    """Send the sheet image to Claude, validate, save scorecard.json. Takes ~20-90 s."""
    key = config.api_key()
    if not key:
        raise sheet_reader.SheetReadError("no_key", "The Claude API key is missing. Paste it in Settings (or add "
                                                    "ANTHROPIC_API_KEY to .env when running start.bat), then click Retry.")
    d = matches.match_dir(match_id)
    m = matches.load(match_id)
    if not m.get("sheet"):
        raise HTTPException(400, "Add a score sheet first.")
    if m["sheet"].get("url"):
        raise HTTPException(400, "This sheet came from a link — import it again instead of reading a photo.")
    if not m.get("batter"):
        raise HTTPException(400, "Enter your name as it's written on the sheet.")
    settings = config.load_settings()
    tokens = load_tokens()
    img = sheet_reader.prepare_image(d / m["sheet"]["file"], display_copy=d / "work" / "sheet_display.jpg")
    result = sheet_reader.read_sheet(img, m["batter"], settings["model"], tokens, key,
                                     on_usage=lambda model, u: usage.record(match_id, "sheet", model, u),
                                     aliases=settings.get("other_names") or [])
    return _store_scorecard(d, match_id, result, settings["model"])


def _store_scorecard(d: Path, match_id: str, result, source: str, sheet: dict | None = None) -> dict:
    """Save a fresh reading/import. The match is re-read under its lock: a sheet read takes up to a minute."""
    sc = Scorecard(**result.model_dump(), model=source, read_at=datetime.now().isoformat(timespec="seconds"))
    config.write_json_atomic(d / "scorecard.raw.json", sc.model_dump())  # untouched reading/import, for reference
    config.write_json_atomic(d / "scorecard.json", sc.model_dump())
    with matches.lock(match_id):
        with matches.edit(match_id) as m:
            if sheet is not None:
                m["sheet"] = sheet
            matches.advance(m, "sheet")
        if m.get("auto_name") and sc.match.team_us and sc.match.team_them:
            day = sc.match.date or m["created"][:10]
            m = matches.rename(m, f"{day} {sc.match.team_us} v {sc.match.team_them}")
    return _full(m["id"])


class UrlIn(BaseModel):
    url: str


@router.post("/api/matches/{match_id}/import-url")
def import_url(match_id: str, body: UrlIn):
    """Import the score sheet from a Spawtz league page. Exact values, no API key needed."""
    d = matches.match_dir(match_id)
    m = matches.load(match_id)
    if not m.get("batter"):
        raise HTTPException(400, "Enter your name as it's written on the sheet.")
    url = spawtz.check_url(body.url)
    html = spawtz.fetch(url)
    result = spawtz.parse(html, m["batter"], url, config.load_settings().get("other_names") or [])
    # Keep a script-free snapshot of the page as the "original sheet".
    snapshot = re.sub(r"<script\b.*?</script\s*>", "", html, flags=re.S | re.I)
    snapshot = re.sub(r"<img\b[^>]*>", "", snapshot, flags=re.I)  # share buttons etc. would be blocked anyway
    tmp = d / "source" / "scoresheet.html.part"
    tmp.write_text(snapshot, encoding="utf-8")
    config.replace_with_retry(tmp, d / "source" / "scoresheet.html")
    (d / "work" / "sheet_display.jpg").unlink(missing_ok=True)
    sheet = {"file": "source/scoresheet.html", "name": "Spawtz score sheet", "size": len(snapshot), "url": url}
    return _store_scorecard(d, match_id, result, "spawtz import", sheet)


@router.get("/api/matches/{match_id}/sheet-html")
def sheet_html(match_id: str):
    p = matches.match_dir(match_id) / "source" / "scoresheet.html"
    if not p.exists():
        raise HTTPException(404, "No imported score sheet")
    from fastapi.responses import HTMLResponse
    # Shown in a sandboxed iframe; the CSP blocks scripts and any external loads.
    return HTMLResponse(p.read_text(encoding="utf-8"), headers={
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:", "Cache-Control": "no-store"})


class ScorecardIn(BaseModel):
    scorecard: dict
    confirm: bool = False


@router.put("/api/matches/{match_id}/scorecard")
def save_scorecard(match_id: str, body: ScorecardIn):
    d = matches.match_dir(match_id)
    try:
        sc = Scorecard.model_validate(body.scorecard)
    except ValidationError as e:
        raise HTTPException(400, f"Scorecard is invalid: {e.errors()[0]['msg']}") from e
    v = validate(sc)
    if body.confirm:
        sc.continued_with_errors = not v["ok"]
        with matches.edit(match_id) as m:
            matches.advance(m, "sync")
    config.write_json_atomic(d / "scorecard.json", sc.model_dump())
    return {"scorecard": sc.model_dump(), "validation": v}


class CatchesIn(BaseModel):
    ids: list[str]               # wicket ids ("5.2") of caught wickets I took


@router.put("/api/matches/{match_id}/catches")
def set_catches(match_id: str, body: CatchesIn):
    """2.1: the sheet has no fielder names, so I mark the catches I took (on Sheet check or in Review)."""
    from ..scorecard import wickets as wickets_of
    sc = config.read_json(matches.match_dir(match_id) / "scorecard.json")
    caught = {w["id"] for w in wickets_of(sc) if w["how"] == "caught"} if sc else set()
    bad = [i for i in body.ids if i not in caught]
    if bad:
        raise HTTPException(400, f"Not a caught wicket on the sheet: {', '.join(bad)}")
    with matches.edit(match_id) as m:
        m["my_catches"] = sorted(set(body.ids), key=lambda x: tuple(int(p) for p in x.split(".")))
    return {"my_catches": m["my_catches"]}
