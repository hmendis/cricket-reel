"""Phase 10 (R37, R38, R39, R40, G4): local-only API, safe names, no off-site redirects, rotating redacted
log, and a feedback bundle with no secrets or outside paths."""
import io
import json
import logging
import os
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import config, desktop, feedback, main, matches, redact, reel, spawtz
from test_review import synced_match

FAKE_KEY = "sk-ant-api03-FAKEKEYfakekey1234567890abcdefghijklmnop"


@pytest.fixture
def client(tmp_data):
    return TestClient(main.app)


def test_foreign_host_and_origin_are_refused(client):
    assert client.get("/api/status").status_code == 200
    assert client.get("/api/status", headers={"host": "evil.example:8000"}).status_code == 403          # DNS rebinding
    assert client.post("/api/matches", json={"batter": "x"}, headers={"origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/matches", json={"batter": "x"}, headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert client.post("/api/matches", json={"batter": "x"}, headers={"origin": "http://testserver"}).status_code == 200


def test_desktop_token_is_required_and_given_to_the_page(client, monkeypatch):
    monkeypatch.setattr(main, "APP_TOKEN", "launch-token-123")
    c = TestClient(main.app)
    assert c.get("/api/status").status_code == 403
    page = c.get("/")                                   # the app's own page hands out the cookie
    assert "cr_token=launch-token-123" in page.headers.get("set-cookie", "") and "samesite=strict" in page.headers["set-cookie"].lower()
    assert c.get("/api/status").status_code == 200      # TestClient keeps the cookie


def test_music_name_must_be_one_the_upload_made():
    assert reel.Reel(music="music.mp3").music == "music.mp3"
    for bad in ("..\\..\\secret.txt", "../x.mp3", "C:/x/music.mp3", "music.exe"):
        with pytest.raises(ValueError):
            reel.Reel(music=bad)


def test_spawtz_redirect_off_site_is_refused():
    h = spawtz._NoRedirect()
    with pytest.raises(spawtz.ImportError_):
        h.redirect_request(None, None, 302, "Found", {}, "http://127.0.0.1:8000/api/matches")
    import urllib.request
    req = urllib.request.Request("https://yourcentre.spawtz.com/a")
    assert h.redirect_request(req, None, 302, "Found", {}, "https://yourcentre.spawtz.com/b") is not None


def test_redaction(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    inside = str(config.MATCHES_DIR / "2026-11-04_Sons" / "match.json")
    s = redact.text(f"key {FAKE_KEY} password=hunter2 token: abc123def Authorization: Bearer abcdefghijklmnopqrstuvwxyz "
                    f"file C:\\Users\\someone\\Documents\\tax\\return.pdf and {inside}")
    assert FAKE_KEY not in s and "hunter2" not in s and "abc123def" not in s and "abcdefghijklmnopqrstuvwxyz" not in s
    assert "Documents" not in s and "[outside path]" in s
    assert redact.text(inside) == "<matches>\\2026-11-04_Sons\\match.json"
    d = redact.data({"api_key": "x", "password": "y", "batter_name": "Alex", "nested": [{"Token": "z"}]})
    assert d == {"api_key": "[removed]", "password": "[removed]", "batter_name": "Alex", "nested": [{"Token": "[removed]"}]}
    assert redact.text("2026-11-04_Sons-Of-Pitches-v-Jumped-the-Shark-2") == "2026-11-04_Sons-Of-Pitches-v-Jumped-the-Shark-2"


def test_feedback_bundle_has_no_secrets(client, monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    config.save_settings({"batter_name": "Alex"})
    (config.CONFIG_DIR / "logs").mkdir()
    (config.CONFIG_DIR / "logs" / "app.log").write_text(
        f"started\nusing key {FAKE_KEY}\nopened C:\\Users\\someone\\Desktop\\private notes.txt\npassword=letmein\n", encoding="utf-8")
    feedback.install_ring()
    logging.getLogger("app.test").warning("sync failed reading D:\\Personal\\video.mp4 with token=sekrit999")
    mid, _ = synced_match(client)
    with matches.edit(mid) as m:
        m["notes_path"] = "C:\\Users\\someone\\Pictures\\x.jpg"
    r = client.post("/api/feedback", json={"message": f"Pinning was off. My key is {FAKE_KEY}", "screen": {"route": "sync", "ball": "2.3"},
                                           "match_id": mid}).json()
    z = zipfile.ZipFile(r["path"])
    names = z.namelist()
    assert {"feedback.json", "environment.json", "logs.txt", "match/match.json", "match/scorecard.json"} <= set(names)
    blob = "\n".join(z.read(n).decode("utf-8") for n in names)
    for secret in (FAKE_KEY, "letmein", "sekrit999", "someone", "Personal"):
        assert secret not in blob, secret
    assert "Pinning was off" in blob and "sync failed" in blob and json.loads(z.read("feedback.json"))["screen"]["ball"] == "2.3"
    assert r["name"].endswith("_sync.zip") and os.path.dirname(r["path"]) == str(feedback.folder())


def test_log_rotates_at_the_limit(tmp_path):
    tmp_path = tmp_path / "logs"
    tmp_path.mkdir()
    log = desktop.RotatingLog(tmp_path / "app.log", max_bytes=200, keep=3)
    for i in range(60):
        log.write(f"line {i:03d} {'x' * 40}\n")
    log.f.close()
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == ["app.log", "app.log.1", "app.log.2"]
    assert all(p.stat().st_size < 400 for p in tmp_path.iterdir())
    log2 = desktop.RotatingLog(tmp_path / "b.log")
    log2.write(f"key={FAKE_KEY}\n")
    log2.f.close()
    assert FAKE_KEY not in (tmp_path / "b.log").read_text()


def test_urls_are_not_mistaken_for_paths():
    assert redact.text("from https://yourcentre.spawtz.com/Leagues/x") == "from https://yourcentre.spawtz.com/Leagues/x"
