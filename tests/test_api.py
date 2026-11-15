import io
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import config, main, sheet_reader
from app.scorecard import SheetRead
from conftest import sample_sheet


@pytest.fixture
def client(tmp_data):
    return TestClient(main.app)


def png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (300, 400), "white").save(buf, "PNG")
    return buf.getvalue()


def new_match(client, batter="Alex"):
    r = client.post("/api/matches", json={"name": "", "batter": batter, "remember": True})
    assert r.status_code == 200, r.text
    return r.json()


def test_status_and_settings(client):
    s = client.get("/api/status").json()
    assert s["model"] == "claude-opus-5-5"
    assert "claude-sonnet-5-5" in s["models"]
    r = client.put("/api/settings", json={"model": "claude-sonnet-5-5", "batter_name": "Alex"})
    assert r.json()["model"] == "claude-sonnet-5-5"
    assert client.put("/api/settings", json={"model": "gpt-4"}).status_code == 400


def test_create_requires_batter_and_remembers_it(client):
    assert client.post("/api/matches", json={"batter": " "}).status_code == 400
    m = new_match(client)
    assert m["batter"] == "Alex" and m["step"] == "import"
    assert config.load_settings()["batter_name"] == "Alex"
    assert [x["id"] for x in client.get("/api/matches").json()] == [m["id"]]


def test_read_sheet_without_key_gives_clear_error(client, monkeypatch):
    monkeypatch.setattr(config, "api_key", lambda: None)
    m = new_match(client)
    client.post(f"/api/matches/{m['id']}/sheet", files={"file": ("sheet.png", png_bytes(), "image/png")})
    r = client.post(f"/api/matches/{m['id']}/read-sheet")
    assert r.status_code == 422 and r.json()["code"] == "no_key"
    assert ".env" in r.json()["error"]


def test_sheet_upload_rejects_wrong_type(client):
    m = new_match(client)
    r = client.post(f"/api/matches/{m['id']}/sheet", files={"file": ("sheet.txt", b"hello", "text/plain")})
    assert r.status_code == 400


def test_full_import_flow(client, monkeypatch):
    monkeypatch.setattr(config, "api_key", lambda: "test-key")
    seen = {}

    def fake_read(img, batter, model, tokens, key, client=None, on_usage=None, aliases=None):
        if on_usage:
            on_usage(model, {"input_tokens": 4000, "output_tokens": 2500})
        seen.update(batter=batter, model=model, key=key, img=len(img))
        return SheetRead.model_validate(sample_sheet())

    monkeypatch.setattr(sheet_reader, "read_sheet", fake_read)
    m = new_match(client)
    r = client.post(f"/api/matches/{m['id']}/sheet", files={"file": ("photo.png", png_bytes(), "image/png")})
    assert r.status_code == 200 and r.json()["sheet"]["name"] == "photo.png"
    assert client.get(f"/api/matches/{m['id']}/sheet-image").headers["content-type"] == "image/jpeg"

    full = client.post(f"/api/matches/{m['id']}/read-sheet").json()
    assert seen["batter"] == "Alex" and seen["key"] == "test-key" and seen["img"] > 0
    # Folder renamed from the sheet's date and teams
    mid = full["match"]["id"]
    assert mid == "2026-11-06_X-RAYTED-v-Lions" and full["match"]["name"] == "2026-11-06 X-RAYTED v Lions"
    assert (config.MATCHES_DIR / mid / "scorecard.raw.json").exists()
    assert not full["validation"]["ok"]

    sc = full["scorecard"]
    sc["overs"][2]["balls"][1].update(code="5", unsure=False)
    r = client.put(f"/api/matches/{mid}/scorecard", json={"scorecard": sc})
    assert r.json()["validation"]["ok"]
    r = client.put(f"/api/matches/{mid}/scorecard", json={"scorecard": sc, "confirm": True})
    assert r.json()["scorecard"]["continued_with_errors"] is False
    lst = client.get("/api/matches").json()
    assert lst[0]["step"] == "sync" and lst[0]["summary"]["runs"] == 30

    assert client.delete(f"/api/matches/{mid}").json()["ok"]
    assert client.get("/api/matches").json() == []


def test_invalid_scorecard_rejected(client):
    m = new_match(client)
    bad = sample_sheet()
    bad["overs"][0]["balls"][0]["facer"] = "someone"
    assert client.put(f"/api/matches/{m['id']}/scorecard", json={"scorecard": bad}).status_code == 400


def test_bad_match_id(client):
    assert client.get("/api/matches/..%5C..%5Cwindows").status_code == 404
    assert client.get("/api/matches/nope").status_code == 404


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs FFmpeg")
def test_video_upload_probe_and_order(client, tmp_path):
    def make(name, w, h, rate):
        p = tmp_path / name
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={w}x{h}:rate={rate}:duration=1",
                        "-f", "lavfi", "-i", "sine=duration=1", "-shortest", "-pix_fmt", "yuv420p", str(p)], check=True)
        return p.read_bytes()

    m = new_match(client)
    r = client.post(f"/api/matches/{m['id']}/videos", files={"file": ("a.mp4", make("a.mp4", 270, 480, 25), "video/mp4")})
    v = r.json()["videos"][0]
    assert v["probe"]["ok"] and v["probe"]["vertical"] and v["probe"]["fps"] == 25 and v["probe"]["has_audio"]
    r = client.post(f"/api/matches/{m['id']}/videos", files={"file": ("b.mp4", make("b.mp4", 480, 270, 30), "video/mp4")})
    vids = r.json()["videos"]
    assert not vids[1]["probe"]["vertical"] and vids[1]["probe"]["fps"] == 30
    order = [vids[1]["file"], vids[0]["file"]]
    assert [x["file"] for x in client.put(f"/api/matches/{m['id']}/videos/order", json={"files": order}).json()["videos"]] == order
    r = client.delete(f"/api/matches/{m['id']}/videos", params={"file": vids[0]["file"]})
    assert len(r.json()["videos"]) == 1
    assert client.post(f"/api/matches/{m['id']}/videos", files={"file": ("x.avi", b"..", "video/avi")}).status_code == 400


def test_app_starts_and_stops_cleanly(tmp_data):
    """The lifespan (Job Object, log capture, cancelling jobs on shutdown) runs without errors."""
    with TestClient(main.app) as c:
        assert c.get("/api/status").status_code == 200


def test_step_only_moves_forward(tmp_data):
    from app import matches
    m = {"step": "review"}
    assert matches.advance(m, "arrange")["step"] == "arrange"
    assert matches.advance(m, "sheet")["step"] == "arrange"  # reading the sheet again doesn't undo progress
    assert matches.advance({"step": "damaged"}, "import")["step"] == "import"
