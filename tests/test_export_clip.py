"""2.2: "Export as clip" - a per-clip flag, on by default for kept highlights, shared by Review and Export."""
from fastapi.testclient import TestClient

from app import config, export, main, matches, review
from test_review import synced_match


def test_default_is_kept_highlights_only():
    assert review.export_on({"keep": True, "wid": "12.1", "code": "c"})                 # a wicket in the field
    assert review.export_on({"keep": True, "code": "4", "kind": "big"})                 # a big shot, 4+
    assert review.export_on({"keep": True, "code": "1", "star": True})                  # starred
    assert not review.export_on({"keep": True, "code": "2"})
    assert not review.export_on({"keep": False, "code": "6"})                           # not kept: never
    assert not review.export_on({"keep": True, "code": "", "source": "manual"})
    assert not review.export_on({"keep": True, "code": "6", "export_clip": False})      # my choice wins
    assert review.export_on({"keep": True, "code": "0", "export_clip": True})


def test_flag_saved_kept_through_resync_and_used_by_export(tmp_data):
    c = TestClient(main.app)
    mid, res = synced_match(c)
    clips = c.get(f"/api/matches/{mid}/review").json()["clips"]
    assert all(x["export_clip"] is None for x in clips)  # nothing set yet: the default rule applies
    big = [x["index"] for x in clips if x["keep"] and x["code"].isdigit() and int(x["code"]) >= 4]
    assert big and c.get(f"/api/matches/{mid}/export").json()["export_clips"] == big
    # toggle: one big shot off, a single on
    one = next(x for x in clips if x["code"] == "1")
    for x in clips:
        if x["index"] == big[0]:
            x["export_clip"] = False
        if x["index"] == one["index"]:
            x["export_clip"] = True
    c.put(f"/api/matches/{mid}/clips", json={"clips": clips})
    want = sorted(big[1:] + [one["index"]])
    assert sorted(c.get(f"/api/matches/{mid}/export").json()["export_clips"]) == want
    # the plan's default clips are the flagged ones; an explicit list still wins
    plan = export.plan(mid, {"reels": []})
    assert sorted(f["index"] for f in plan["files"] if f["kind"] == "clip") == want
    assert export.plan(mid, {"reels": [], "clips": []})["files"] == []
    assert c.post(f"/api/matches/{mid}/export/plan", json={"reels": []}).json()["files"]
    # a re-sync keeps the choice (as it keeps a star)
    res = {**res, "created": "later"}
    config.write_json_atomic(matches.match_dir(mid) / "sync.json", res)
    again = {x["index"]: x for x in c.get(f"/api/matches/{mid}/review").json()["clips"]}
    assert again[big[0]]["export_clip"] is False and again[one["index"]]["export_clip"] is True
