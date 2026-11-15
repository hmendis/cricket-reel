"""Phase 5 (R2, R4, R6, R23): fast alignment with the same results, flat-memory motion, candidates re-used."""
import json
import random
import shutil
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import main, matches, media, sync
from conftest import make_av, sample_sheet, wait_for_job

FIX = Path(__file__).parent / "fixtures"


def scenario(seed, n_overs=4, noise=600, dur=900.0):
    """A pair's overs with plausible ball gaps, 10% of balls without a sound, and lots of random noise."""
    rnd = random.Random(seed)
    overs = []
    for o in range(n_overs):
        balls = [["me" if rnd.random() < 0.5 else "partner", rnd.choice(["0", "1", "2", "4", "c", "nb"])]
                 for _ in range(rnd.randint(6, 8))]
        overs.append({"number": o + 1, "bowler": "B", "total_sheet": 0,
                      "balls": [{"facer": f, "code": c, "unsure": False, "note": ""} for f, c in balls]})
    sc = {"match": {}, "batter": {}, "partner": {}, "overs": overs}
    t, cs = rnd.uniform(60, 150), []
    for o in overs:
        for bi, _ in enumerate(o["balls"]):
            t += rnd.uniform(15, 25) + (rnd.uniform(20, 40) if bi == 0 else 0)
            if rnd.random() > 0.1:
                cs.append({"t": t + rnd.uniform(-0.05, 0.05), "s": 0.8, "audio": rnd.uniform(0.5, 1), "motion": rnd.uniform(0.4, 1)})
    for _ in range(noise):
        cs.append({"t": rnd.uniform(0, dur), "s": 0.5, "audio": rnd.uniform(0, 0.7), "motion": rnd.uniform(0, 0.6)})
    cs.sort(key=lambda c: c["t"])
    pins = {3: next(c["t"] for c in cs if c["t"] > 200)} if seed % 3 == 0 else None
    return sc, cs, pins


def test_alignment_matches_the_previous_version():
    """Times and confidence for 12 seeded matches, recorded with the old loop-based alignment."""
    ref = json.loads((FIX / "align_v1.json").read_text())
    for seed, want in enumerate(ref):
        sc, cs, pins = scenario(seed)
        res = sync.run(sc, cs, 900.0, None, pins)
        if pins:  # pins changed meaning on purpose in phase 6: they land exactly, not on any sound within 3 s
            assert all(res["deliveries"][i]["t"] == pytest.approx(t, abs=sync.PIN_SNAP) for i, t in pins.items())
            continue
        got = [[d["t"], d["conf"]] for d in res["deliveries"]]
        assert got == want, f"seed {seed}"


def test_long_match_aligns_quickly():
    """About 60 deliveries against 5,000 candidate sounds (a 90-minute match) in well under 5 s."""
    sc, cs, _ = scenario(7, n_overs=8, noise=5000, dur=5400.0)
    dels = sync.deliveries_from_scorecard(sc)
    t0 = time.perf_counter()
    assign, _ = sync._align(dels, cs, 0, 5400, 22, 25)
    assert time.perf_counter() - t0 < 5 and len(assign) > 0.8 * len(dels)


def test_motion_sink_matches_the_whole_array_calculation():
    rng = np.random.default_rng(3)
    w, h = media.MOTION_W, media.MOTION_H
    frames = rng.integers(0, 255, (57, h, w), dtype=np.uint8)
    raw = frames.tobytes()
    sink = media.MotionSink()
    pos = 0
    while pos < len(raw):  # FFmpeg hands over chunks of any size, cutting frames in half
        n = int(rng.integers(1, 3 * w * h))
        sink(raw[pos:pos + n])
        pos += n
    f = frames.astype(np.float32)
    want = np.concatenate([[0.0], np.abs(np.diff(f, axis=0)).mean(axis=(1, 2))])
    assert np.allclose(sink.result(), want, atol=1e-4)


@pytest.mark.slow
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs FFmpeg")
def test_resync_reuses_candidates_and_keeps_the_sensitivity(tmp_data, tmp_path):
    c = TestClient(main.app)
    mid = c.post("/api/matches", json={"batter": "Alex"}).json()["id"]
    make_av(tmp_path / "v.mp4", 8)
    c.post(f"/api/matches/{mid}/videos", files={"file": ("v.mp4", (tmp_path / "v.mp4").read_bytes(), "video/mp4")})
    c.put(f"/api/matches/{mid}/scorecard", json={"scorecard": sample_sheet(fix_misread=True), "confirm": True})
    d = matches.match_dir(mid)

    j = wait_for_job(c, c.post(f"/api/matches/{mid}/sync", json={"sensitivity": 0.8}).json()["id"])
    assert j["status"] == "done", j
    stamp = (d / "work" / "candidates.json").stat().st_mtime_ns
    assert json.loads((d / "sync.json").read_text())["sensitivity"] == 0.8

    # Re-sync with my fixes: same media, same (remembered) sensitivity → detection is skipped.
    j = wait_for_job(c, c.post(f"/api/matches/{mid}/resync-fixes").json()["job"]["id"])
    assert j["status"] == "done", j
    assert (d / "work" / "candidates.json").stat().st_mtime_ns == stamp
    assert json.loads((d / "sync.json").read_text())["sensitivity"] == 0.8

    # A new sensitivity → detection runs again.
    j = wait_for_job(c, c.post(f"/api/matches/{mid}/sync", json={"sensitivity": 0.2}).json()["id"])
    assert (d / "work" / "candidates.json").stat().st_mtime_ns != stamp


def test_second_sync_request_is_refused_while_one_runs(tmp_data, monkeypatch):
    from app import jobs
    c = TestClient(main.app)
    mid = c.post("/api/matches", json={"batter": "Alex"}).json()["id"]
    gate = jobs.start("sync", mid, ["x"], lambda job: time.sleep(0.5))
    r = c.post(f"/api/matches/{mid}/resync-fixes")
    assert r.status_code == 409 and "already running" in r.json()["detail"]
    deadline = time.monotonic() + 10
    while gate.status in jobs.ACTIVE and time.monotonic() < deadline:
        time.sleep(0.05)
