"""Phase 7 (R3, R13): import without a second copy, linked originals, sprite thumbnails."""
import shutil
import threading

import pytest
from fastapi.testclient import TestClient
from PIL import Image
import io

from app import config, main, matches, media
from conftest import make_av

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs FFmpeg")


@pytest.fixture
def client(tmp_data):
    return TestClient(main.app)


def test_raw_upload_writes_once_into_the_match(client):
    mid = client.post("/api/matches", json={"batter": "Alex"}).json()["id"]
    body = b"\x00" * (3 * 1024 * 1024 + 17)
    m = client.post(f"/api/matches/{mid}/videos/raw", params={"name": "game.mp4"}, content=body,
                    headers={"Content-Type": "application/octet-stream"}).json()
    v = m["videos"][0]
    d = matches.match_dir(mid)
    assert v["name"] == "game.mp4" and v["size"] == len(body) and (d / v["file"]).read_bytes() == body
    assert not list((d / "source").glob("*.part")) and "probe" in v
    assert client.post(f"/api/matches/{mid}/videos/raw", params={"name": "x.avi"}, content=b"..").status_code == 400


def test_linked_video_is_used_in_place_and_never_deleted(client, tmp_path):
    mid = client.post("/api/matches", json={"batter": "Alex"}).json()["id"]
    orig = tmp_path / "Insta360" / "VID_0001.mp4"
    orig.parent.mkdir()
    orig.write_bytes(b"original footage")
    m = client.post(f"/api/matches/{mid}/videos/link", json={"paths": [str(orig)]}).json()
    v = m["videos"][0]
    assert v["linked"] and v["path"] == str(orig) and v["size"] == len(b"original footage")
    assert not list((matches.match_dir(mid) / "source").glob("*VID_0001*"))  # nothing copied
    # adding the same file twice doesn't duplicate it
    assert len(client.post(f"/api/matches/{mid}/videos/link", json={"paths": [str(orig)]}).json()["videos"]) == 1
    client.delete(f"/api/matches/{mid}/videos", params={"file": v["file"]})
    assert orig.read_bytes() == b"original footage" and matches.load(mid)["videos"] == []
    assert client.post(f"/api/matches/{mid}/videos/link", json={"paths": [str(tmp_path / "nope.mp4")]}).status_code == 400


def test_relink_after_the_original_moved(client, tmp_path):
    mid = client.post("/api/matches", json={"batter": "Alex"}).json()["id"]
    a = tmp_path / "a.mp4"
    a.write_bytes(b"0123456789")
    v = client.post(f"/api/matches/{mid}/videos/link", json={"paths": [str(a)]}).json()["videos"][0]
    moved = tmp_path / "moved" / "a.mp4"
    moved.parent.mkdir()
    a.rename(moved)
    other = tmp_path / "other.mp4"
    other.write_bytes(b"different size")
    assert client.put(f"/api/matches/{mid}/videos/relink", json={"file": v["file"], "path": str(other)}).status_code == 400
    m = client.put(f"/api/matches/{mid}/videos/relink", json={"file": v["file"], "path": str(moved)}).json()
    assert m["videos"][0]["path"] == str(moved)


@needs_ffmpeg
@pytest.mark.slow
def test_prep_reads_a_linked_file_and_serves_sprite_thumbnails(client, tmp_path):
    mid = client.post("/api/matches", json={"batter": "Alex"}).json()["id"]
    src = tmp_path / "elsewhere.mp4"
    make_av(src, 12)
    m = client.post(f"/api/matches/{mid}/videos/link", json={"paths": [str(src)]}).json()
    d = matches.match_dir(mid)
    st = media.prepare(d, m["videos"], lambda f: None, threading.Event())
    assert st["offsets"][0]["path"] == str(src) and st["thumbs"]["sprite"]
    img = client.get(f"/api/matches/{mid}/thumb/7")
    assert img.status_code == 200 and Image.open(io.BytesIO(img.content)).size == (90, 160)
    assert client.get(f"/api/matches/{mid}/sprite/0").status_code == 200
    assert client.get(f"/api/matches/{mid}/sprite/5").status_code == 404
    # the export maps clip times onto the linked original
    from app import export
    segs = export.source_mapper(d, matches.load(mid))
    assert segs(3.0, 2.0) == [(src, 3.0, 2.0)]
    # if it's moved away, prep says where it was
    src.rename(tmp_path / "gone.mp4")
    v = dict(m["videos"][0], size=m["videos"][0]["size"] + 1)  # force a rebuild
    with pytest.raises(media.MediaError, match="isn't where it was"):
        media.prepare(d, [v], lambda f: None, threading.Event())
