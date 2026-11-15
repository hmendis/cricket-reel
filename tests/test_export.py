import shutil
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from app import config, export, main, matches
from conftest import wait_for_job
from test_review import synced_match

def ffmpeg_needed(f):
    return pytest.mark.slow(pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs FFmpeg")(f))


def test_names():
    c = {"over": 10, "ball": 3, "code": "4", "kind": "big", "label": "BIG SHOT · 4"}
    assert export.clip_name(c) == "over10_ball03_4runs.mp4"
    assert export.clip_name(dict(c, code="1", kind="runs")) == "over10_ball03_1run.mp4"
    assert export.clip_name(dict(c, code="c", kind="wicket")) == "over10_ball03_wicket.mp4"
    assert export.clip_name(dict(c, code="0", kind="runs")) == "over10_ball03_dot.mp4"
    assert export.result_slug(dict(c, code="nb²", kind="extra", label="NO BALL")) == "noball"
    m, sc = {"created": "2026-11-06T10:00"}, {"match": {"date": "2026-11-06", "team_us": "X-RAYTED", "team_them": "Lions"}}
    assert export.reel_name(m, sc) == "2026-11-06_X-RAYTED-v-Lions_batting_reel.mp4"   # 2.1: named after the kind of reel
    assert export.reel_name(m, sc, "allround") == "2026-11-06_X-RAYTED-v-Lions_allround_reel.mp4"
    assert export.reel_name(m, sc, "bowlfield") == "2026-11-06_X-RAYTED-v-Lions_bowling-fielding_reel.mp4"
    w = {"over": 12, "ball": 1, "code": "b", "kind": "wicket", "label": "WICKET · BOWLED", "wid": "12.1", "role": "bowling", "t": 1800.0}
    assert export.clip_name(w) == "their-over12_ball01_bowling_bowled.mp4"
    assert export.clip_name(dict(w, label="WICKET · RUN OUT", role="fielding")) == "their-over12_ball01_fielding_run-out.mp4"
    assert export.clip_name({"source": "manual", "role": "fielding", "label": "GOOD STOP", "t": 2530.4}) == "fielding_good-stop_42m10s.mp4"


def test_encoder_args_tag_bt709_and_bitrate():
    for enc in ("h264_qsv", "libx264"):
        a = " ".join(export.encoder_args(18, enc))
        assert "-profile:v high" in a and "-colorspace bt709" in a and "-color_range tv" in a and "-maxrate 25M" in a
    assert "-crf 16" in " ".join(export.encoder_args(18, "libx264"))
    assert "-b:v 18M" in " ".join(export.encoder_args(18, "h264_qsv"))


def test_platform_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    assert export.mbps() == 40 and export.fits(200) == ["TikTok"] and export.fits(60) == ["TikTok", "Reels", "Shorts"]
    config.write_json_atomic(tmp_path / "export.json", {"reels": {"max_s": 900}, "mbps": 30})
    assert export.platforms()["reels"]["max_s"] == 900 and export.mbps() == 30 and export.fits(200) == ["TikTok", "Reels"]


def test_source_mapping_across_files(tmp_path):
    (tmp_path / "work").mkdir()
    (tmp_path / "source").mkdir()
    for n in ("a.mp4", "b.mp4"):
        (tmp_path / "source" / n).write_bytes(b"x")
    config.write_json_atomic(tmp_path / "work" / "media.json", {"offsets": [
        {"file": "source/a.mp4", "start": 0, "duration": 100}, {"file": "source/b.mp4", "start": 100, "duration": 50}]})
    (tmp_path / "work" / "cfr_02.mp4").write_bytes(b"x")  # file 2 was VFR → use its 25 fps working copy
    segs = export.source_mapper(tmp_path, {})
    assert segs(10, 3) == [(tmp_path / "source" / "a.mp4", 10, 3)]
    two = segs(98.5, 3)
    assert [p.name for p, _, _ in two] == ["a.mp4", "cfr_02.mp4"]
    assert two[0][1:] == pytest.approx((98.5, 1.5)) and two[1][1:] == pytest.approx((0.0, 1.5))


def make_match_with_media(c, tmp_path, dur=60):
    mid, _ = synced_match(c)
    c.get(f"/api/matches/{mid}/review")
    d = matches.match_dir(mid)
    src = d / "source" / "01_v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size=540x960:rate=25:duration={dur}",
                    "-f", "lavfi", "-i", f"sine=frequency=500:duration={dur}", "-shortest", "-pix_fmt", "yuv420p", str(src)], check=True)
    config.write_json_atomic(d / "work" / "media.json", {"offsets": [{"file": "source/01_v.mp4", "start": 0, "duration": dur}], "duration": dur})
    # squeeze the clips into the short test video
    m = matches.load(mid)
    for k, cl in enumerate(m["clips"]):
        cl["t"] = 3.0 + k * 3.5
    matches.save(m)
    return mid


def wait(c, job_id):
    return wait_for_job(c, job_id)


@ffmpeg_needed
def test_export_files_spec(tmp_data, tmp_path, monkeypatch):
    monkeypatch.setattr(export, "pick_encoder", lambda: "libx264")
    c = TestClient(main.app)
    mid = make_match_with_media(c, tmp_path)
    c.get(f"/api/matches/{mid}/arrange")
    clips = matches.load(mid)["clips"]
    body = {"reel": True, "clips": [clips[0]["index"]]}
    plan = c.post(f"/api/matches/{mid}/export/plan", json=body).json()
    # E1: one file per item, straight into exports/, no per-platform copies
    assert [f["kind"] for f in plan["files"]] == ["reel", "clip"] and {f["folder"] for f in plan["files"]} == {""}
    assert plan["files"][0]["fits"] == ["TikTok", "Reels", "Shorts"] and plan["mbps"] == 40
    j = wait(c, c.post(f"/api/matches/{mid}/export", json=body).json()["id"])
    files = j["result"]["files"]
    assert j["status"] == "done" and all(f["status"] == "done" for f in files), files
    exports = matches.match_dir(mid) / "exports"
    assert sorted(p.name for p in exports.iterdir()) == sorted(f["name"] for f in files)
    reel_file = next(f for f in files if f["kind"] == "reel")
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,profile,pix_fmt,color_space,color_primaries,color_transfer,color_range,r_frame_rate",
                          "-of", "default=nw=1", reel_file["path"]], capture_output=True, text=True).stdout
    for want in ("width=1080", "height=1920", "profile=High", "pix_fmt=yuv420p", "color_space=bt709", "color_primaries=bt709",
                 "color_transfer=bt709", "color_range=tv", "r_frame_rate=25/1"):
        assert want in out, (want, out)
    ln = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", reel_file["path"], "-af", "ebur128", "-f", "null", "-"],
                        capture_output=True, text=True).stderr
    lufs = float([l for l in ln.splitlines() if l.strip().startswith("I:")][-1].split()[1])
    assert lufs == pytest.approx(-14, abs=1)
    assert matches.load(mid)["step"] == "exported"
    # R10: the audio is encoded once (AAC 192k, 48 kHz) and no render temp files are left
    a = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_name,sample_rate",
                        "-of", "default=nw=1", reel_file["path"]], capture_output=True, text=True).stdout
    assert "codec_name=aac" in a and "sample_rate=48000" in a
    assert not list((matches.match_dir(mid) / "work" / "export").glob("render_*"))


@ffmpeg_needed
def test_failed_file_reported_and_others_continue(tmp_data, tmp_path, monkeypatch):
    calls = {"n": 0}
    real = export.encoder_args

    def flaky(mbps, enc):
        calls["n"] += 1
        return ["-c:v", "no_such_encoder"] if calls["n"] == 1 else real(mbps, "libx264")

    monkeypatch.setattr(export, "encoder_args", flaky)
    monkeypatch.setattr(export, "pick_encoder", lambda: "libx264")
    c = TestClient(main.app)
    mid = make_match_with_media(c, tmp_path)
    clips = matches.load(mid)["clips"]
    body = {"reel": False, "clips": [clips[0]["index"], clips[1]["index"]]}
    j = wait(c, c.post(f"/api/matches/{mid}/export", json=body).json()["id"])
    st = [f["status"] for f in j["result"]["files"]]
    assert st == ["failed", "done"] and j["result"]["files"][0]["error"]
    assert not list((matches.match_dir(mid) / "exports").glob("*.part.mp4"))


def test_export_requires_something(tmp_data):
    c = TestClient(main.app)
    mid, _ = synced_match(c)
    c.get(f"/api/matches/{mid}/review")
    assert c.post(f"/api/matches/{mid}/export", json={"reel": False, "clips": []}).status_code == 400
    assert c.put("/api/settings", json={"encoder": "nvenc"}).status_code == 400
    assert c.put("/api/settings", json={"encoder": "x264"}).json()["encoder"] == "x264"
    assert export.pick_encoder() == "libx264"
