from fastapi.testclient import TestClient

from app import config, main, matches, review, sync
from conftest import sample_sheet
from test_sync import make_cands, truth_times


def synced_match(client):
    m = client.post("/api/matches", json={"batter": "Alex"}).json()
    sc = sample_sheet(fix_misread=True)
    client.put(f"/api/matches/{m['id']}/scorecard", json={"scorecard": sc, "confirm": True})
    res = sync.run(sc, make_cands(truth_times(sc)), 900.0)
    config.write_json_atomic(matches.match_dir(m["id"]) / "sync.json", res)
    return m["id"], res


def test_clips_built_for_my_balls_only(tmp_data):
    c = TestClient(main.app)
    mid, res = synced_match(c)
    r = c.get(f"/api/matches/{mid}/review").json()
    mine = [d for d in res["deliveries"] if d["facer"] == "me"]
    assert [x["index"] for x in r["clips"]] == [d["index"] for d in mine]
    assert all(x["before"] == 1.0 and x["after"] == 2.0 and not x["confirmed"] for x in r["clips"])
    # K2: dots (and leg-side wides) start as not kept, everything else is kept
    assert all(x["keep"] == (x["code"] != "0") and x["auto"] == ("dot ball" if x["code"] == "0" else None) for x in r["clips"])
    assert len(r["partner"]) == len(res["deliveries"]) - len(mine)
    assert r["clips"][0]["label"] and r["duration"] is None  # no media in this test


def test_edits_survive_a_resync(tmp_data):
    c = TestClient(main.app)
    mid, res = synced_match(c)
    clips = c.get(f"/api/matches/{mid}/review").json()["clips"]
    clips[0].update(t=clips[0]["t"] + 1.5, edited=True, confirmed=True, star=True)
    clips[1].update(keep=False, after=3.0)
    assert c.put(f"/api/matches/{mid}/clips", json={"clips": clips}).status_code == 200
    # new sync run (different timestamp) → clips rebuilt, my edits kept
    res2 = dict(res, created="2099-01-01T00:00:00")
    for d in res2["deliveries"]:
        d["t"] = d["t"] + 0.3
    config.write_json_atomic(matches.match_dir(mid) / "sync.json", res2)
    new = c.get(f"/api/matches/{mid}/review").json()["clips"]
    assert new[0]["t"] == clips[0]["t"] and new[0]["star"] and new[0]["edited"]
    assert new[1]["keep"] is False and new[1]["after"] == 3.0
    assert abs(new[1]["t"] - (clips[1]["t"] + 0.3)) < 1e-6  # not edited → takes the new sync time
    assert matches.load(mid)["step"] == "review"


def test_save_rejects_bad_clips(tmp_data):
    c = TestClient(main.app)
    mid, _ = synced_match(c)
    clips = c.get(f"/api/matches/{mid}/review").json()["clips"]
    bad = [dict(clips[0], before=50)] + clips[1:]
    assert c.put(f"/api/matches/{mid}/clips", json={"clips": bad}).status_code == 400
    assert c.put(f"/api/matches/{mid}/clips", json={"clips": clips[1:]}).status_code == 409


def test_fixes_become_pins(tmp_data):
    c = TestClient(main.app)
    mid, _ = synced_match(c)
    clips = c.get(f"/api/matches/{mid}/review").json()["clips"]
    clips[2].update(t=clips[2]["t"] + 2.0, edited=True)
    clips[4].update(confirmed=True)
    c.put(f"/api/matches/{mid}/clips", json={"clips": clips})
    pins = review.pins_from_fixes(mid)
    assert pins == {str(clips[2]["index"]): round(clips[2]["t"], 3), str(clips[4]["index"]): round(clips[4]["t"], 3)}


def test_review_needs_a_sync(tmp_data):
    c = TestClient(main.app)
    m = c.post("/api/matches", json={"batter": "Alex"}).json()
    assert c.get(f"/api/matches/{m['id']}/review").status_code == 400
