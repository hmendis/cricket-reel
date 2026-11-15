"""2.2: the Look step is gone. Output goes out as the camera recorded it, even for a match saved with a look."""
import inspect
import re

from fastapi.testclient import TestClient

from app import config, main, matches, render
from test_review import synced_match

JS = config.STATIC_DIR / "js"
GRADE = ("eq=", "colorbalance", "colorlevels", "hqdn3d", "unsharp", "deflicker", "lut3d")


def test_look_routes_and_files_are_gone(tmp_data):
    c = TestClient(main.app)
    mid, _ = synced_match(c)
    assert c.get(f"/api/matches/{mid}/look").status_code in (404, 405)
    assert c.put(f"/api/matches/{mid}/look", json={"look": {}}).status_code in (404, 405)
    assert not (JS / "look.js").exists() and not (config.ROOT / "app" / "look.py").exists()
    assert "look" not in inspect.signature(render.build_command).parameters


def test_a_saved_look_is_ignored_and_the_look_step_still_opens(tmp_data, tmp_path):
    c = TestClient(main.app)
    mid, _ = synced_match(c)
    c.get(f"/api/matches/{mid}/review")
    c.get(f"/api/matches/{mid}/arrange")
    with matches.edit(mid) as m:
        m["look"] = {"preset": "punchy", "exposure": 60, "contrast": 20, "saturation": 30, "warmth": 15, "sharp": 40,
                     "denoise": 20, "deflicker": True}
        m["step"] = "look"
    full = c.get(f"/api/matches/{mid}").json()
    assert full["match"]["step"] == "look"
    assert [x for x in c.get("/api/matches").json() if x["id"] == mid][0]["step"] == "look"
    for screen in ("review", "arrange", "export"):
        assert c.get(f"/api/matches/{mid}/{screen}").status_code == 200, screen
    assert "look" not in c.get(f"/api/matches/{mid}/export").json()
    # the render command has no colour grade, whatever the match has saved
    m = matches.load(mid)
    from app import reel
    r = reel.of(m)
    cmd, _ = render.build_command(r, matches.clips_by_index(m), tmp_path / "proxy.mp4", tmp_path / "out.mp4", tmp_path / "w")
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert not any(g in graph for g in GRADE), graph
    # the step still moves forward from look
    with matches.edit(mid) as m:
        matches.advance(m, "exported")
    assert matches.load(mid)["step"] == "exported"


def test_six_steps_in_the_top_bar():
    shell = (JS / "shell.js").read_text(encoding="utf-8")
    steps = re.findall(r"\{ key: '(\w+)', name:", shell)
    assert steps == ["import", "sync", "review", "arrange", "export", "describe"]
    assert "'look'" in shell  # still in the order, so old matches open
    assert "if (!m) return '';" in shell  # no step bar on Home
    main_js = (JS / "main.js").read_text(encoding="utf-8")
    assert "look.js" not in main_js and "+ nav()" not in main_js
    for f in ("import", "sync", "review", "arrange", "export", "describe", "sheet"):
        assert "of 7" not in (JS / f"{f}.js").read_text(encoding="utf-8"), f
