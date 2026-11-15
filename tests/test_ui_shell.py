"""Phase 13: the new shell (G1, G2, G5), camera and lens (U2), library posters, and the UI files themselves."""
import re

from fastapi.testclient import TestClient

from app import config, main, matches

STATIC = config.STATIC_DIR


def test_no_logos_and_version_in_the_shell():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '<script type="module" src="js/main.js">' in html and "<svg" not in html
    shell = (STATIC / "js" / "shell.js").read_text(encoding="utf-8")
    assert 'class="appname"' in shell and "status.version" in shell
    for p in list((STATIC / "js").glob("*.js")) + [STATIC / "styles.css"]:
        s = p.read_text(encoding="utf-8")
        assert not re.search(r"LOGO|class=\"brand|logo\.(svg|png)", s), p.name  # the text app name only
    icon = (STATIC / "icon.svg").read_text(encoding="utf-8")
    assert ">CR</text>" in icon


def test_every_module_import_resolves():
    """A missing file or a wrong relative path breaks the whole app at load time."""
    for p in (STATIC / "js").rglob("*.js"):
        s = p.read_text(encoding="utf-8")
        for spec in re.findall(r"""(?:from|import)\s*\(?\s*['"](\.[^'"]+)['"]""", s):
            assert (p.parent / spec).resolve().exists(), f"{p.name} imports missing {spec}"


def test_ui_files_are_revalidated(tmp_data):
    c = TestClient(main.app)
    for path in ("/", "/styles.css", "/js/main.js", "/js/arrange.js"):
        r = c.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache", path
    assert "no-cache" not in c.get("/api/status").headers.get("cache-control", "")


def test_camera_and_lens_saved_with_the_match_and_remembered(tmp_data):
    c = TestClient(main.app)
    st = c.get("/api/status").json()
    assert st["settings"]["camera"] == "Insta360 GO Ultra" and st["settings"]["lens"] == "action"
    assert "Insta360 GO Ultra" in st["cameras"] and st["lenses"]["mega"] == "MegaView"
    m = c.post("/api/matches", json={"name": "2026-11-12 A v B", "batter": "Me"}).json()
    full = c.patch(f"/api/matches/{m['id']}", json={"camera": "Insta360 X5", "lens": "mega"}).json()
    assert full["match"]["camera"] == {"model": "Insta360 X5", "lens": "mega"}
    s = c.get("/api/status").json()["settings"]
    assert s["camera"] == "Insta360 X5" and s["lens"] == "mega"  # asked once, remembered for the next match
    assert c.patch(f"/api/matches/{m['id']}", json={"lens": "fisheye"}).status_code == 400
    assert c.put("/api/settings", json={"lens": "fisheye"}).status_code == 400


def test_library_poster_is_your_first_ball(tmp_data):
    c = TestClient(main.app)
    m = c.post("/api/matches", json={"name": "2026-11-12 A v B", "batter": "Me"}).json()
    assert c.get("/api/matches").json()[0]["poster"] is None
    d = matches.match_dir(m["id"])
    (d / "work" / "thumbs").mkdir(parents=True)
    config.write_json_atomic(d / "sync.json", {"deliveries": [{"facer": "partner", "t": 50.0}, {"facer": "me", "t": 71.6}]})
    row = c.get("/api/matches").json()[0]
    assert row["poster"] == 71 and row["clips"] == 0 and row["exports"] == 0
