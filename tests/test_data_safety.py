"""Phase 2 (R18, R25, R26, R28): match.json is never corrupted or overwritten by a concurrent edit."""
import io
import json
import threading

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import config, main, matches


def png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (60, 80), "white").save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def client(tmp_data):
    return TestClient(main.app)


def test_concurrent_edits_lose_nothing(tmp_data):
    mid = matches.create("Concurrency", "Alex")["id"]
    errors = []

    def writer(i):
        try:
            for k in range(5):
                with matches.edit(mid) as m:
                    m[f"w{i}_{k}"] = i * 10 + k
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    m = matches.load(mid)
    assert all(m[f"w{i}_{k}"] == i * 10 + k for i in range(20) for k in range(5))
    # no temp files left behind next to match.json
    assert not list(matches.match_dir(mid).glob("*.tmp"))


def test_edit_does_not_write_when_nothing_changed_or_on_error(tmp_data):
    mid = matches.create("No-op", "Alex")["id"]
    path = matches.match_dir(mid) / "match.json"
    stamp = path.stat().st_mtime_ns
    with matches.edit(mid) as m:
        _ = m["name"]
    assert path.stat().st_mtime_ns == stamp
    with pytest.raises(RuntimeError):
        with matches.edit(mid) as m:
            m["batter"] = "Changed"
            raise RuntimeError("boom")
    assert matches.load(mid)["batter"] == "Alex"


def test_atomic_write_flushes_and_keeps_backup(tmp_path):
    p = tmp_path / "x.json"
    config.write_json_atomic(p, {"v": 1}, backup=True)
    config.write_json_atomic(p, {"v": 2}, backup=True)
    assert json.loads(p.read_text()) == {"v": 2}
    assert json.loads((tmp_path / "x.json.bak").read_text()) == {"v": 1}
    assert not list(tmp_path.glob("*.tmp"))


def test_damaged_match_is_listed_and_others_still_load(client):
    good = client.post("/api/matches", json={"name": "Good match", "batter": "Alex"}).json()["id"]
    bad = client.post("/api/matches", json={"name": "Bad match", "batter": "Alex"}).json()["id"]
    d = matches.match_dir(bad)
    (d / "match.json").write_text("{ not json", encoding="utf-8")
    (d / "match.json.bak").unlink(missing_ok=True)
    listed = {m["id"]: m for m in client.get("/api/matches").json()}
    assert listed[good].get("damaged") is None
    assert listed[bad]["damaged"] is True and "damaged" in listed[bad]["error"]
    assert client.get(f"/api/matches/{bad}").status_code == 500


def test_damaged_match_recovers_from_backup(client):
    mid = client.post("/api/matches", json={"name": "Recover me", "batter": "Alex"}).json()["id"]
    client.patch(f"/api/matches/{mid}", json={"batter": "Alex C"})  # second save → .bak holds the first version
    d = matches.match_dir(mid)
    (d / "match.json").write_text("", encoding="utf-8")  # e.g. power cut mid-write on the old code
    m = client.get(f"/api/matches/{mid}").json()["match"]
    assert m["id"] == mid and m["name"]


def test_bad_replacement_sheet_keeps_the_old_one(client):
    mid = client.post("/api/matches", json={"batter": "Alex"}).json()["id"]
    assert client.post(f"/api/matches/{mid}/sheet", files={"file": ("first.png", png_bytes(), "image/png")}).status_code == 200
    r = client.post(f"/api/matches/{mid}/sheet", files={"file": ("broken.png", b"not an image", "image/png")})
    assert r.status_code == 422
    d = matches.match_dir(mid)
    m = matches.load(mid)
    assert m["sheet"]["name"] == "first.png" and (d / m["sheet"]["file"]).exists()
    assert (d / "work" / "sheet_display.jpg").exists()
    assert not list((d / "source").glob("incoming_*")) and not (d / "work" / "sheet_display.new.jpg").exists()


def test_reuploading_a_removed_name_never_overwrites(client):
    mid = client.post("/api/matches", json={"batter": "Alex"}).json()["id"]
    up = lambda body: client.post(f"/api/matches/{mid}/videos", files={"file": ("game.mp4", body, "video/mp4")}).json()  # noqa: E731
    up(b"first")
    m = up(b"second")
    first, second = m["videos"][0]["file"], m["videos"][1]["file"]
    client.delete(f"/api/matches/{mid}/videos", params={"file": first})
    m = up(b"third")
    d = matches.match_dir(mid)
    files = [v["file"] for v in m["videos"]]
    assert len(files) == len(set(files)) == 2 and second in files
    assert (d / second).read_bytes() == b"second"
    assert {(d / f).read_bytes() for f in files} == {b"second", b"third"}
    assert not list((d / "source").glob("*.part"))
