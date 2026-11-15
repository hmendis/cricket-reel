"""Phase 14: every screen is a module the router can load, and the data the new screens rely on."""
import re

from fastapi.testclient import TestClient

from app import config, main
from test_review import synced_match

JS = config.STATIC_DIR / "js"


def test_every_route_has_a_screen_module():
    router = (JS / "main.js").read_text(encoding="utf-8")
    routes = dict(re.findall(r"^\s+(\w+): \(\) => import\('\./(\w+)\.js'\)", router, re.M))
    assert set(routes) == {"home", "import", "sheet", "sync", "review", "arrange", "export", "describe", "settings"}
    for name, file in routes.items():
        s = (JS / f"{file}.js").read_text(encoding="utf-8")
        assert "export async function mount(" in s, name
    shell = (JS / "shell.js").read_text(encoding="utf-8")
    assert "/legacy/" not in shell and not (config.STATIC_DIR / "legacy").exists()  # the old interface is gone
    assert "key: 'describe'" in shell  # six steps in the top bar


def test_arrange_gets_the_text_each_clip_shows(tmp_data):
    c = TestClient(main.app)
    mid, _ = synced_match(c)
    c.get(f"/api/matches/{mid}/review")
    d = c.get(f"/api/matches/{mid}/arrange").json()
    first = str(d["reel"]["entries"][0]["index"])
    assert d["reel"]["texts"] is None  # a new reel starts from the hook / outro / label settings…
    hook = d["texts"][first][0]
    assert hook["id"] == "hook" and hook["show"] == "first3" and 9 < hook["y"] < 80  # …placed out of the zones
    # once edited in the new screen, the texts are saved as they are
    texts = {first: [dict(hook, text="BIG NIGHT", y=40)]}
    r = c.put(f"/api/matches/{mid}/reel", json={"reel": {**d["reel"], "texts": texts}}).json()
    assert r["reel"]["texts"][first][0]["text"] == "BIG NIGHT"
    assert c.get(f"/api/matches/{mid}/arrange").json()["texts"][first][0]["y"] == 40


def test_screens_get_the_waveform_as_bytes_only(tmp_data):
    c = TestClient(main.app)
    mid, _ = synced_match(c)
    assert "waveform" not in c.get(f"/api/matches/{mid}/sync").json()
    assert "waveform" not in c.get(f"/api/matches/{mid}/review").json()
