"""Phase 6 (S1, S2, S3, S4, K2): over slots, first/last shot tags, the stance check, per-over re-sync, keep rules."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import config, main, matches, review, stance, sync
from conftest import sample_sheet
from test_review import synced_match
from test_sync import make_cands, truth_times


def test_over_slots_follow_the_sheet_and_the_gaps():
    dels = sync.deliveries_from_scorecard(sample_sheet(fix_misread=True))
    slots = sync.over_slots(dels, 100.0, 20.0, 30.0)
    assert [s["over"] for s in slots] == [9, 10, 11, 12]
    assert slots[0] == {"over": 9, "start": 100.0, "end": 100.0 + 6 * 20 + 30}
    assert all(a["end"] == b["start"] for a, b in zip(slots, slots[1:]))


def test_result_has_slots_and_first_last_ball():
    sc = sample_sheet(fix_misread=True)
    truth = truth_times(sc)
    r = sync.run(sc, make_cands(truth), 900.0, batting_start=95.0)
    assert len(r["slots"]) == 4 and r["slots"][0]["start"] == 95.0
    assert r["first_ball"] == pytest.approx(truth[0], abs=0.2) and r["last_ball"] == pytest.approx(truth[-1], abs=0.2)


def test_first_and_last_shot_tags_pull_everything_into_place():
    """Strong decoys exactly one ball early would fool the plain alignment; the two tags fix it."""
    sc = sample_sheet(fix_misread=True)
    truth = truth_times(sc, start=200)
    decoys = [{"t": t - 20.0, "s": 0.95, "audio": 0.95, "motion": 0.95} for t in truth[:8]]
    cands = sorted(make_cands(truth, dur=1100) + decoys, key=lambda c: c["t"])
    dels = sync.deliveries_from_scorecard(sc)
    mine = [i for i, d in enumerate(dels) if d["facer"] == "me"]
    r = sync.run(sc, cands, 1100.0, anchors={"first": truth[mine[0]], "last": truth[mine[-1]]})
    assert max(abs(d["t"] - truth[d["index"]]) for d in r["deliveries"]) < 1.0
    assert r["deliveries"][mine[0]]["why"] == "pinned" and r["anchors"]["first"] == truth[mine[0]]


def test_pinning_realigns_only_that_over():
    sc = sample_sheet(fix_misread=True)
    truth = truth_times(sc)
    cands = make_cands(truth)
    first = sync.run(sc, cands, 900.0)
    dels = sync.deliveries_from_scorecard(sc)
    k = next(i for i, d in enumerate(dels) if d["over"] == 11 and d["ball"] == 3)
    after = sync.realign_over(sc, cands, first, 11, {k: truth[k] + 0.6})
    changed = {d["over"] for a, d in zip(first["deliveries"], after["deliveries"]) if a["t"] != d["t"] or a["conf"] != d["conf"]}
    assert changed == {11}
    assert after["deliveries"][k]["t"] == pytest.approx(truth[k] + 0.6, abs=sync.PIN_SNAP) and after["realigned_over"] == 11


def test_pin_endpoint_resyncs_one_over(tmp_data):
    c = TestClient(main.app)
    mid, res = synced_match(c)
    d = matches.match_dir(mid)
    config.write_json_atomic(d / "work" / "candidates.json", make_cands(truth_times(sample_sheet(fix_misread=True))))
    before = config.read_json(d / "sync.json")
    k = next(x["index"] for x in before["deliveries"] if x["over"] == 10)
    out = c.post(f"/api/matches/{mid}/sync/pin", json={"index": k, "t": before["deliveries"][k]["t"] + 0.5}).json()
    after = out["sync"]["deliveries"]
    assert {x["over"] for x, y in zip(before["deliveries"], after) if x["t"] != y["t"]} <= {10}
    assert out["pins"] == {str(k): round(before["deliveries"][k]["t"] + 0.5, 3)}
    # unpin
    out = c.post(f"/api/matches/{mid}/sync/pin", json={"index": k, "t": None}).json()
    assert out["pins"] == {}
    assert c.post(f"/api/matches/{mid}/sync/pin", json={"index": 999, "t": 1}).status_code == 400


def test_anchor_and_reference_endpoints(tmp_data):
    c = TestClient(main.app)
    mid, _ = synced_match(c)
    assert c.put(f"/api/matches/{mid}/sync/anchors", json={"first": 120.5, "last": 640.25}).json()["anchors"] == {"first": 120.5, "last": 640.25}
    m = matches.load(mid)
    assert stance.reference_time(m) == pytest.approx(119.0)  # 1.5 s before the first shot, automatically
    c.put(f"/api/matches/{mid}/sync/reference", json={"t": 200.0})
    assert stance.reference_time(matches.load(mid)) == 200.0
    c.put(f"/api/matches/{mid}/sync/reference", json={"off": True})
    assert stance.reference_time(matches.load(mid)) is None


def _stance_file(path, n_frames, stance_at, rng):
    """Random-looking frames, except a fixed 'stance' picture for 2 s before each time in stance_at."""
    look = rng.integers(0, 255, (stance.H, stance.W, 3), dtype=np.uint8)
    fr = rng.integers(0, 255, (n_frames, stance.H, stance.W, 3), dtype=np.uint8)
    for t in stance_at:
        a, b = int((t - 2.0) * stance.FPS), int((t - 0.5) * stance.FPS)
        noise = rng.integers(-8, 8, (b - a, stance.H, stance.W, 3))
        fr[a:b] = np.clip(look.astype(int) + noise, 0, 255).astype(np.uint8)
    fr.tofile(path)


def test_stance_scores_moments_and_alignment(tmp_path):
    rng = np.random.default_rng(5)
    sc = sample_sheet(fix_misread=True)
    truth = truth_times(sc)
    dels = sync.deliveries_from_scorecard(sc)
    mine_t = [t for t, d in zip(truth, dels) if d["facer"] == "me"]
    path = tmp_path / stance.FILE
    _stance_file(path, int(900 * stance.FPS), mine_t, rng)
    s = stance.scores(path, mine_t[0] - 1.0)
    mo = stance.moments(s)
    assert len(mo) == len(mine_t)
    assert all(stance.before(s, t) > 0.9 for t in mine_t)
    partner_t = [t for t, d in zip(truth, dels) if d["facer"] != "me"]
    assert all(stance.before(s, t) == 0 for t in partner_t)
    # A strong decoy sound 1.5 s before each of my balls: without stance it wins, with stance the real hit wins.
    cands = make_cands(truth)
    decoys = [{"t": t - 1.5, "s": 0.95, "audio": 1.0, "motion": 1.0} for t in mine_t]
    all_c = sorted(cands + decoys, key=lambda c: c["t"])
    plain = sync.run(sc, all_c, 900.0)
    helped = sync.run(sc, stance.annotate(all_c, s), 900.0)
    err = lambda r: max(abs(d["t"] - truth[d["index"]]) for d in r["deliveries"] if d["facer"] == "me")  # noqa: E731
    assert err(plain) > 1.0 and err(helped) < 0.2


def test_keep_rules():
    assert review.auto_drop_reason("0", None) == "dot ball"
    assert review.auto_drop_reason("ls", None) == "leg-side wide"
    assert review.auto_drop_reason("ls2", None) == "leg-side wide"
    assert review.auto_drop_reason("nb", None) is None
    assert review.auto_drop_reason("nb", {"nb": True}) == "no-ball"
    assert review.auto_drop_reason("0", {"dot": False}) is None
    assert review.auto_drop_reason("2", None) is None and review.auto_drop_reason("c", None) is None


def test_keep_rules_follow_settings(tmp_data):
    c = TestClient(main.app)
    assert c.put("/api/settings", json={"auto_drop": {"dot": False, "ls": True, "nb": False}}).status_code == 200
    mid, _ = synced_match(c)
    clips = c.get(f"/api/matches/{mid}/review").json()["clips"]
    assert all(x["keep"] for x in clips if x["code"] == "0")
