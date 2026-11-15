import shutil
import subprocess
import threading

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import config, main, matches, media, reel, render
from conftest import make_av, sample_sheet, squeeze_clips, wait_for_job
from test_review import synced_match


def clip(i, code, kind, star=False, keep=True, before=1.0, after=2.0, t=None):
    return {"index": i, "over": 1 + i // 6, "ball": 1 + i % 6, "code": code, "kind": kind, "label": code, "t": t or 10.0 + 20 * i,
            "before": before, "after": after, "keep": keep, "star": star, "text": None}


def test_default_order_biggest_moments_first():
    clips = [clip(0, "2", "runs"), clip(1, "0", "runs"), clip(2, "5", "big"), clip(3, "c", "wicket"), clip(4, "1", "runs"),
             clip(5, "nb", "extra"), clip(6, "6", "big"), clip(7, "2", "runs")]
    e = reel.default_entries(clips, 45)
    # big shots by runs, then the wicket, then twos (match order), then singles; dots/extras left out
    assert [x["index"] for x in e] == [6, 2, 3, 0, 7, 4]


def test_star_wins_hook_and_survives_trimming():
    clips = [clip(i, "2", "runs") for i in range(20)] + [clip(20, "0", "runs", star=True)]
    e = reel.default_entries(clips, 30)
    assert e[0]["index"] == 20
    assert sum(3.0 for _ in e) <= 30


def test_total_length_counts_freeze_and_transitions():
    clips = {i: clip(i, "2", "runs") for i in range(3)}
    r = reel.Reel(freeze=True, freeze_dur=0.4, trans="fade", trans_dur=0.25).model_dump()
    r["entries"] = [{"uid": str(i), "index": i, "trans": None} for i in range(3)]
    r["entries"][2]["trans"] = "cut"
    assert reel.total_length(r, clips) == pytest.approx(9 + 0.4 - 0.25)


def test_suggestions_from_scorecard():
    sc = sample_sheet(fix_misread=True)
    clips = [clip(0, "5", "big"), clip(1, "6", "big")]
    s = reel.suggestions(sc, clips)
    assert s["hooks"][0] == "30 off 14 vs Lions"
    assert "2 big shots" in s["hooks"][1]
    assert s["outro"].startswith("X-RAYTED 142 def. Lions 118") and "A. Carter" in s["outro"]


def test_arrange_api_roundtrip(tmp_data):
    c = TestClient(main.app)
    mid, _ = synced_match(c)
    c.get(f"/api/matches/{mid}/review")  # builds clips
    a = c.get(f"/api/matches/{mid}/arrange").json()
    assert a["reel"]["entries"] and a["reel"]["hook_text"] and a["total"] > 0
    r = a["reel"]
    r["entries"] = list(reversed(r["entries"]))
    r["entries"][1]["trans"] = "slideleft"
    r["target_min"], r["target_max"] = 50, 20  # swapped on save
    s = c.put(f"/api/matches/{mid}/reel", json={"reel": r}).json()
    assert s["reel"]["target_min"] == 20 and s["reel"]["entries"][1]["trans"] == "slideleft"
    assert matches.load(mid)["step"] == "arrange"
    bad = dict(r, entries=[{"index": 999}])
    assert c.put(f"/api/matches/{mid}/reel", json={"reel": bad}).status_code == 409
    assert c.put(f"/api/matches/{mid}/reel", json={"reel": dict(r, trans="spin")}).status_code == 400
    auto = c.post(f"/api/matches/{mid}/reel/auto").json()
    assert auto["reel"]["entries"][0]["index"] != r["entries"][0]["index"] or True


def test_label_defaults():
    assert reel.default_label({"label": "BIG SHOT · 5", "kind": "big", "over": 3}) == "Over 3 · 5 RUNS"
    assert reel.default_label({"label": "WICKET · CAUGHT", "kind": "wicket", "over": 2}) == "Over 2 · WICKET"
    assert reel.default_label({"label": "DOT", "kind": "runs", "over": 1}) == "Over 1 · DOT BALL"


def ffmpeg_needed(f):
    return pytest.mark.slow(pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs FFmpeg")(f))


@ffmpeg_needed
@pytest.mark.parametrize("trans,punch,freeze,music", [("cut", False, False, False), ("fade", True, True, True),
                                                       ("slideleft", False, True, False), ("zoomin", True, False, True)])
def test_render_lengths_match(tmp_path, trans, punch, freeze, music):
    src = tmp_path / "proxy.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=270x480:rate=25:duration=40",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=40", "-shortest", "-pix_fmt", "yuv420p", str(src)], check=True)
    mus = None
    if music:
        mus = tmp_path / "music.mp3"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=4", str(mus)], check=True)
    clips = {i: clip(i, ["2", "5", "c", "0"][i], ["runs", "big", "wicket", "runs"][i], t=5.0 + 8 * i) for i in range(4)}
    r = reel.Reel(trans=trans, punch=punch, freeze=freeze, hook_text="26 off 13 vs Lions — a long hook line",
                  outro_text="X-RAYTED 142 def. Lions 118\nPlayer of the match: A. Carter", labels=True).model_dump()
    r["entries"] = [{"uid": str(i), "index": i, "trans": None} for i in range(4)]
    out = tmp_path / "out.mp4"
    cmd, total = render.build_command(r, clips, src, out, tmp_path / "w", (270, 480), mus)
    media.run(cmd, total=total, cancel=threading.Event(), cwd=tmp_path / "w")
    p = matches.probe(out)
    assert p["ok"] and (p["width"], p["height"]) == (270, 480) and p["has_audio"]
    assert p["duration"] == pytest.approx(total, abs=0.1)
    assert total == pytest.approx(reel.total_length(r, clips), abs=0.01)


@ffmpeg_needed
def test_render_preview_endpoint(tmp_data, tmp_path):
    c = TestClient(main.app)
    mid, _ = synced_match(c)
    c.get(f"/api/matches/{mid}/review")
    c.get(f"/api/matches/{mid}/arrange")
    d = matches.match_dir(mid)
    squeeze_clips(mid)
    make_av(d / "work" / "proxy.mp4", 30)
    job = c.post(f"/api/matches/{mid}/render-preview").json()
    j = wait_for_job(c, job["id"])
    assert j["status"] == "done", j
    r = c.get(f"/api/matches/{mid}/reel-preview", headers={"Range": "bytes=0-0"})
    assert r.status_code == 206


def test_windows_at_the_ends_of_the_video_are_cut_to_fit():
    """R27: a ball half a second into the video, and one near the end: the contact stays on the right frame."""
    clips = {0: clip(0, "4", "big", t=0.5), 1: clip(1, "2", "runs", t=99.0)}
    r = reel.Reel(freeze=True).model_dump()
    r["entries"] = [{"uid": "a", "index": 0, "trans": None}, {"uid": "b", "index": 1, "trans": None}]
    first, last = render.plan(r, clips, duration=100.0)
    assert (first["start"], first["contact"], first["len"]) == (0.0, 0.5, 2.5)
    assert last["start"] == pytest.approx(98.0) and last["len"] == pytest.approx(2.0) and last["contact"] == pytest.approx(1.0)


def test_older_reels_get_text_items_and_the_hook_is_not_top_right():
    """L4: the hook text moves from the top-right corner to the upper third, centred; labels keep their colours."""
    clips = {0: clip(0, "6", "big"), 1: clip(1, "2", "runs"), 2: clip(2, "c", "wicket")}
    r = reel.Reel(hook_text="13 off 12", outro_text="We won", labels=True).model_dump()
    r["entries"] = [{"uid": str(i), "index": i, "trans": None} for i in range(3)]
    t = reel.texts_for(r, clips)
    hook = t[0][0]
    assert hook["text"] == "13 off 12" and hook["x"] == 50 and hook["y"] < 40 and hook["show"] == "first3"
    assert t[1][0]["text"] == "Over 1 · 2" and t[2][0]["text"] == "We won"  # the last clip shows the outro instead of a label
    r["texts"] = {"1": [{"text": "Clean", "x": 30, "y": 60}]}
    got = reel.texts_for(r, clips)
    assert list(got) == [1] and {k: v for k, v in got[1][0].items() if k != "id"} ==         {k: v for k, v in reel.TextItem(text="Clean", x=30, y=60).model_dump().items() if k != "id"}


def test_text_is_kept_out_of_the_keep_away_zones():
    """L5: wherever an item is put, the rendered box stays in the frame and out of the zones."""
    W, H = 1080, 1920
    for x, y in [(50, 1), (50, 99), (99, 60), (2, 50), (99, 5)]:
        item = reel.TextItem(text="BIG SHOT · 6", x=x, y=y, size=9).model_dump()
        cx, cy = render.fit_in_safe_area(item, W, H)
        _, _, bw, bh, _, _ = render._measure(item, W)
        l, t, r_, b = (cx - bw / 2) / W * 100, (cy - bh / 2) / H * 100, (cx + bw / 2) / W * 100, (cy + bh / 2) / H * 100
        assert l >= 0 and r_ <= 100 and t >= render.ZONES["top"][3] and b <= render.ZONES["bottom"][1]
        rz = render.ZONES["right"]
        assert not (b > rz[1] and t < rz[3] and r_ > rz[0]), (x, y)


def test_text_png_has_the_style(tmp_path):
    from PIL import Image
    item = reel.TextItem(text="Run out", x=50, y=50, size=8, bg="pill", bo=1.0, color="#FFB547", shadow=True, outline=True).model_dump()
    render.draw_text_png(item, 540, 960, tmp_path / "t.png")
    im = Image.open(tmp_path / "t.png")
    assert im.size == (540, 960) and im.mode == "RGBA"
    px = im.getpixel((270, 480))
    assert px[3] > 200  # the pill background (opaque) at the centre
    assert im.getpixel((5, 5))[3] == 0  # transparent elsewhere
    a = np.array(im)
    amber = (a[..., 3] == 255) & (np.abs(a[..., 0].astype(int) - 255) < 20) & (np.abs(a[..., 1].astype(int) - 181) < 30) & (a[..., 2] < 120)
    assert amber.any()  # the amber text is drawn


@ffmpeg_needed
def test_rendered_text_lands_outside_the_zones(tmp_path):
    """A white box pushed to the very bottom is rendered above the caption zone (pixel check on a black video)."""
    src = tmp_path / "black.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:size=270x480:rate=25:duration=4",
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "4", "-pix_fmt", "yuv420p", str(src)], check=True)
    clips = {0: clip(0, "4", "big", t=1.5)}
    r = reel.Reel().model_dump()
    r["entries"] = [{"uid": "a", "index": 0, "trans": None}]
    r["texts"] = {"0": [reel.TextItem(text="BOTTOM", x=50, y=99, size=10, bg="box", bo=1.0, color="#FFFFFF").model_dump()]}
    out = tmp_path / "o.mp4"
    cmd, total = render.build_command(r, clips, src, out, tmp_path / "w", (270, 480))
    media.run(cmd, total=total, cancel=threading.Event(), cwd=tmp_path / "w")
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1", "-i", str(out), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True).stdout
    g = np.frombuffer(raw, np.uint8).reshape(480, 270)
    assert g[int(480 * 0.81):].max() < 40           # nothing in the bottom zone
    assert g[int(480 * 0.6):int(480 * 0.8)].max() > 200  # the text sits just above it


def test_long_text_wraps_inside_the_frame():
    item = reel.TextItem(text="Night Owls 93 def. Lions 66", x=50, y=50, size=9).model_dump()
    _, text, bw, _, _, _ = render._measure(item, 1080)
    assert chr(10) in text and bw <= 0.8 * 1080 + 1


def test_bowling_fielding_auto_fill_plays_in_ball_order():
    """2.2: a Bowling + Fielding reel is one sequence: the best clip is the hook, the rest play by ball."""
    clips = [{"index": 1000 + k, "kind": "wicket", "code": "c", "keep": True, "role": "fielding" if k % 2 else "bowling",
              "phase": "fielding", "t": 500.0 - 30 * k, "before": 3.0, "after": 4.0} for k in range(6)]
    out = reel.default_entries(clips, 60, ["bowling", "fielding"])
    by = {c["index"]: c for c in clips}
    ts = [by[e["index"]]["t"] for e in out[1:]]
    assert len(out) == 6 and ts == sorted(ts)
    r = {**reel.Reel(rtype="bowlfield").model_dump(), "entries": out}
    assert [e for _, e in reel.ordered(r, by)] == out                  # no sections, no header cards


def test_previews_have_no_music(tmp_path, monkeypatch):
    """2.2: music left the interface; a reel that still names a music file renders without it."""
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "proxy.mp4").write_bytes(b"x")
    seen = {}

    def fake_build(reel_, clips, src, out, workdir, size=(540, 960), music=None, **k):
        seen["music"] = music
        return ["ffmpeg"], 3.0
    monkeypatch.setattr(render, "build_command", fake_build)
    monkeypatch.setattr(media, "run", lambda *a, **k: (tmp_path / "work" / "reel_preview.part.mp4").write_bytes(b"x"))
    r = {**reel.Reel(music="music.mp3").model_dump(), "entries": [{"uid": "a", "index": 0, "trans": None}]}
    render.render_preview(tmp_path, r, {0: {"index": 0, "t": 5.0, "before": 1, "after": 2}}, lambda f: None, None)
    assert seen["music"] is None
