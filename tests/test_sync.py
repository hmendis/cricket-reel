import random
import shutil
import subprocess
import threading
import time
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import config, hits, main, media, sync
from conftest import sample_sheet, wait_for_job


def truth_times(sc, start=100.0, gap=20.0, over_extra=30.0):
    ts, t = [], start
    for oi, o in enumerate(sc["overs"]):
        for bi, _ in enumerate(o["balls"]):
            if ts:
                t += gap + (over_extra if bi == 0 else 0)
            ts.append(t)
    return ts


def make_cands(true_ts, noise=80, dur=900.0, seed=1, drop=()):
    rnd = random.Random(seed)
    c = [{"t": t + rnd.uniform(-0.05, 0.05), "s": 0.8, "audio": 0.8, "motion": 0.8} for i, t in enumerate(true_ts) if i not in drop]
    for _ in range(noise):
        a, m = rnd.uniform(0.1, 0.6), rnd.uniform(0.0, 0.5)
        c.append({"t": rnd.uniform(0, dur), "s": 0.5 * a + 0.5 * m, "audio": a, "motion": m})
    return sorted(c, key=lambda x: x["t"])


def test_alignment_recovers_true_times():
    sc = sample_sheet(fix_misread=True)
    truth = truth_times(sc)
    r = sync.run(sc, make_cands(truth), 900.0)
    assert r["ok"], r["error"]
    got = [d["t"] for d in r["deliveries"]]
    assert np.max(np.abs(np.array(got) - np.array(truth))) < 0.2
    assert 18 <= r["gap_ball"] <= 22
    assert r["stats"]["mine_matched"] == r["stats"]["mine"] == 14
    assert all(d["label"] for d in r["deliveries"])


def test_missing_hits_are_interpolated_and_flagged():
    sc = sample_sheet(fix_misread=True)
    truth = truth_times(sc)
    r = sync.run(sc, make_cands(truth, drop=(5, 12)), 900.0)
    for i in (5, 12):  # no real hit: either left unmatched or matched to a weak noise sound - always "needs check"
        d = r["deliveries"][i]
        assert d["conf"] == "low", d
        assert abs(d["t"] - truth[i]) < 8
    others = [d for k, d in enumerate(r["deliveries"]) if k not in (5, 12)]
    assert max(abs(d["t"] - truth[d["index"]]) for d in others) < 0.2
    assert r["ok"]


def test_batting_start_ignores_earlier_decoys():
    sc = sample_sheet(fix_misread=True)
    truth = truth_times(sc, start=300)
    decoys = [{"t": 20.0 + 20 * k, "s": 0.9, "audio": 0.9, "motion": 0.9} for k in range(12)]
    cands = sorted(make_cands(truth, dur=1100) + decoys, key=lambda c: c["t"])
    r = sync.run(sc, cands, 1100.0, batting_start=290)
    assert abs(r["deliveries"][0]["t"] - truth[0]) < 0.2
    assert not r["start_warning"]


def test_pins_override_misleading_audio():
    """Real hits shifted by one ball vs strong decoys: pins at both ends pull the whole innings into place."""
    sc = sample_sheet(fix_misread=True)
    truth = truth_times(sc, start=200)
    decoys = [{"t": t - 20.0, "s": 0.95, "audio": 0.95, "motion": 0.95} for t in truth[:6]]
    cands = sorted(make_cands(truth, dur=1100) + decoys, key=lambda c: c["t"])
    # Pins land exactly where they're put, or on a bat sound within PIN_SNAP (0.12 s) of it.
    r = sync.run(sc, cands, 1100.0, pins={1: truth[1] + 0.08, len(truth) - 1: truth[-1] - 0.1})
    assert abs(r["deliveries"][1]["t"] - truth[1]) < 0.2 and r["deliveries"][1]["why"] == "pinned"
    assert abs(r["deliveries"][-1]["t"] - truth[-1]) < 0.2
    assert max(abs(d["t"] - truth[d["index"]]) for d in r["deliveries"][1:]) < 0.2
    assert r["pins"] and not r["start_warning"]


def test_pin_stays_where_it_was_put():
    """The Fix-ball panel pins the playhead. A pin 0.8 s from the nearest sound keeps its time."""
    sc = sample_sheet(fix_misread=True)
    truth = truth_times(sc)
    r = sync.run(sc, make_cands(truth), 900.0, pins={4: truth[4] + 0.8})
    assert r["deliveries"][4]["t"] == pytest.approx(truth[4] + 0.8, abs=sync.PIN_SNAP) and r["deliveries"][4]["why"] == "pinned"


def test_pin_without_any_sound_nearby_still_lands():
    sc = sample_sheet(fix_misread=True)
    truth = truth_times(sc)
    cands = [c for c in make_cands(truth) if abs(c["t"] - 500) > 5]
    r = sync.run(sc, cands, 900.0, pins={10: 500.0})
    assert r["deliveries"][10]["t"] == pytest.approx(500.0)


def test_too_few_candidates_fails_cleanly():
    sc = sample_sheet(fix_misread=True)
    r = sync.run(sc, [{"t": 10.0, "s": 0.9}, {"t": 50.0, "s": 0.9}], 600.0)
    assert not r["ok"] and "could be matched" in r["error"]


def test_spaced_evenly():
    sc = sample_sheet(fix_misread=True)
    r = sync.spaced_evenly(sc, 100, 600)
    ts = [d["t"] for d in r["deliveries"]]
    assert ts == sorted(ts) and 100 < ts[0] < ts[-1] < 600
    assert all(d["conf"] == "low" for d in r["deliveries"]) and r["even"]


def write_wav(path, sr, y):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())


def test_hit_detection_finds_cracks(tmp_path):
    sr, dur = 22050, 60.0
    rng = np.random.default_rng(0)
    y = rng.normal(0, 0.01, int(sr * dur))
    hit_times = [8.0, 19.5, 31.0, 44.2, 55.0]
    for t in hit_times:  # short broadband crack, decaying in ~30 ms
        n = int(0.04 * sr)
        i = int(t * sr)
        y[i:i + n] += rng.normal(0, 0.6, n) * np.exp(-np.arange(n) / (0.008 * sr))
    wav = tmp_path / "a.wav"
    write_wav(wav, sr, y)
    motion = np.full(int(dur * 10), 20.0)
    for t in hit_times:  # still for 2 s before each hit, moving after
        motion[int((t - 2.5) * 10):int(t * 10)] = 1.0
    cands = hits.detect(wav, motion, 10)
    top = sorted(cands, key=lambda c: -c["s"])[:len(hit_times)]
    found = sorted(c["t"] for c in top)
    assert np.allclose(found, hit_times, atol=0.05), found
    assert all(c["motion"] > 0.6 for c in top)


def ffmpeg_needed(f):
    return pytest.mark.slow(pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs FFmpeg")(f))


def make_video(path, dur=12, rate=25):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size=270x480:rate={rate}:duration={dur}",
                    "-f", "lavfi", "-i", f"sine=frequency=1000:duration={dur}", "-shortest", "-pix_fmt", "yuv420p", str(path)], check=True)


@ffmpeg_needed
def test_media_prepare_and_cache(tmp_path):
    d = tmp_path / "m"
    (d / "source").mkdir(parents=True)
    make_video(d / "source" / "01_a.mp4", dur=6, rate=30)  # constant 30 fps → read directly, no working copy (R11)
    make_video(d / "source" / "02_b.mp4", dur=4)
    from app import matches
    vids = [{"file": f"source/{n}", "name": n, "size": (d / "source" / n).stat().st_size, "probe": matches.probe(d / "source" / n)}
            for n in ("01_a.mp4", "02_b.mp4")]
    seen = []
    st = media.prepare(d, vids, seen.append, threading.Event())
    assert abs(st["duration"] - 10) < 0.3 and seen[-1] == 1.0
    assert not list((d / "work").glob("cfr_*.mp4")) and st["working_copies"] == []
    p = matches.probe(d / "work" / "proxy.mp4")
    assert (p["width"], p["height"], p["fps"]) == (540, 960, 25) and abs(p["duration"] - 10) < 0.3
    assert len(np.load(d / "work" / "motion.npy")) == pytest.approx(100, abs=3)
    assert [p.name for p in (d / "work" / "thumbs").glob("*.jpg")] == ["sprite_000.jpg"]  # R13: 10 s in one sprite
    from PIL import Image
    assert Image.open(d / "work" / "thumbs" / "sprite_000.jpg").size == (900, 1600)
    keys = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-skip_frame", "nokey", "-show_entries",
                           "frame=pts_time", "-of", "csv=p=0", str(d / "work" / "proxy.mp4")], capture_output=True, text=True).stdout.split()
    assert len(keys) == pytest.approx(10, abs=1)  # R12: a keyframe every second
    stamp = (d / "work" / "proxy.mp4").stat().st_mtime_ns
    seen2 = []
    media.prepare(d, vids, seen2.append, threading.Event())  # cached: nothing is rebuilt
    assert (d / "work" / "proxy.mp4").stat().st_mtime_ns == stamp


@ffmpeg_needed
def test_sync_job_end_to_end(tmp_data, tmp_path):
    c = TestClient(main.app)
    m = c.post("/api/matches", json={"batter": "Alex"}).json()
    make_video(tmp_path / "v.mp4", dur=8)
    c.post(f"/api/matches/{m['id']}/videos", files={"file": ("v.mp4", (tmp_path / "v.mp4").read_bytes(), "video/mp4")})
    assert c.post(f"/api/matches/{m['id']}/sync").status_code == 400  # no scorecard yet
    c.put(f"/api/matches/{m['id']}/scorecard", json={"scorecard": sample_sheet(fix_misread=True), "confirm": True})
    job = c.post(f"/api/matches/{m['id']}/sync", json={}).json()
    j = wait_for_job(c, job["id"])
    assert j["status"] == "done", j
    events = c.get(f"/api/jobs/{job['id']}/events").text
    assert events.startswith("data: ") and '"status": "done"' in events
    ov = c.get(f"/api/matches/{m['id']}/sync").json()
    assert ov["sync"] is not None and ov["duration"] == pytest.approx(8, abs=0.3) and ov["has_proxy"]
    assert not ov["sync"]["ok"]  # a test pattern has no bat hits: sync must fail cleanly, not crash
    r = c.post(f"/api/matches/{m['id']}/sync/even", json={"start": 0, "end": 8}).json()
    assert r["sync"]["ok"] and r["sync"]["even"]
    assert c.get(f"/api/matches/{m['id']}/proxy", headers={"Range": "bytes=0-99"}).status_code == 206
    assert c.get(f"/api/matches/{m['id']}/thumb/2").headers["content-type"] == "image/jpeg"
