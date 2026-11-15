"""Phase 3 (R19, R20, R21, R22): FFmpeg never outlives a cancel, a timeout or the app; jobs run one at a time;
a failed prep never damages the previous one; Quick Sync failures fall back to software."""
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from app import config, jobs, matches, media
from conftest import make_av

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs FFmpeg")
LONG = ["-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25:duration=600", "-c:v", "libx264",
        "-preset", "slow", "-f", "null", "-"]


def test_software_fallback_swaps_quick_sync_args():
    cmd = ["ffmpeg", "-hwaccel", "qsv", "-i", "x", "-c:v", "h264_qsv", "-global_quality", "18", "-preset", "faster",
           "-look_ahead", "1", "-pix_fmt", "nv12", "out.mp4"]
    assert media.software_fallback(cmd) == ["ffmpeg", "-i", "x", "-c:v", "libx264", "-crf", "18", "-preset", "faster",
                                            "-pix_fmt", "yuv420p", "out.mp4"]


def test_quick_sync_failure_retries_with_x264(tmp_path, monkeypatch):
    """Any command using h264_qsv that fails is run again with libx264, and Quick Sync stays off afterwards.
    A stand-in program fails whenever it's given h264_qsv, so this doesn't depend on the machine's GPU."""
    monkeypatch.setitem(media._encoder_cache, "h264", "h264_qsv")
    fake = tmp_path / "fake_ffmpeg.py"
    out = tmp_path / "args.txt"
    fake.write_text("\n".join([
        "import sys",
        "if 'h264_qsv' in sys.argv: sys.stderr.write('Error initializing an internal MFX session'); sys.exit(1)",
        f"open({str(out)!r}, 'w').write(' '.join(sys.argv[1:]))",
    ]) + "\n", encoding="utf-8")
    media.run([sys.executable, str(fake), "-c:v", "h264_qsv", "-global_quality", "28", "-preset", "faster", "o.mp4"], timeout=60)
    assert out.read_text() == "-c:v libx264 -crf 28 -preset faster o.mp4"
    assert media.h264_encoder() == "libx264"


@needs_ffmpeg
@pytest.mark.slow
def test_cancel_kills_ffmpeg_and_waits():
    cancel = threading.Event()
    threading.Timer(0.5, cancel.set).start()
    t0 = time.monotonic()
    with pytest.raises(media.Cancelled):
        media.run([media.ffmpeg(), *LONG], cancel=cancel)
    assert time.monotonic() - t0 < 10 and not media._PROCS


@needs_ffmpeg
@pytest.mark.slow
def test_timeout_kills_ffmpeg():
    with pytest.raises(media.MediaError, match="longer than"):
        media.run([media.ffmpeg(), *LONG], timeout=0.5)
    assert not media._PROCS


def _prepped(tmp_path):
    d = tmp_path / "m"
    (d / "source").mkdir(parents=True)
    make_av(d / "source" / "01_a.mp4", 6)
    vids = [{"file": "source/01_a.mp4", "name": "a.mp4", "size": (d / "source" / "01_a.mp4").stat().st_size,
             "probe": matches.probe(d / "source" / "01_a.mp4")}]
    media.prepare(d, vids, lambda f: None, threading.Event())
    return d, vids


def _leftovers(work: Path):
    return [p.name for p in work.iterdir() if p.name in ("prep.new", "thumbs.old") or ".part" in p.name]


@needs_ffmpeg
@pytest.mark.slow
def test_cancelled_prep_keeps_the_previous_one(tmp_path):
    d, vids = _prepped(tmp_path)
    work = d / "work"
    before = (work / "proxy.mp4").read_bytes()
    thumbs = len(list((work / "thumbs").glob("*.jpg")))
    vids[0]["size"] += 1  # pretend the video changed → a full rebuild
    cancel = threading.Event()
    with pytest.raises(media.Cancelled):
        media.prepare(d, vids, lambda f: cancel.set() if f > 0 else None, cancel)
    assert (work / "proxy.mp4").read_bytes() == before
    assert len(list((work / "thumbs").glob("*.jpg"))) == thumbs
    assert not _leftovers(work) and not media._PROCS


@needs_ffmpeg
@pytest.mark.slow
def test_failed_swap_keeps_the_previous_proxy(tmp_path, monkeypatch):
    d, vids = _prepped(tmp_path)
    work = d / "work"
    before = (work / "proxy.mp4").read_bytes()
    real = config.replace_with_retry

    def busy(src, dst, *a, **k):
        if Path(dst).name == "proxy.mp4":
            raise PermissionError("in use")
        return real(src, dst, *a, **k)

    monkeypatch.setattr(config, "replace_with_retry", busy)
    vids[0]["size"] += 1
    with pytest.raises(media.MediaError, match="open somewhere else"):
        media.prepare(d, vids, lambda f: None, threading.Event())
    assert (work / "proxy.mp4").read_bytes() == before and not _leftovers(work)


def test_jobs_run_one_at_a_time():
    spans = []

    def work(job):
        t0 = time.monotonic()
        time.sleep(0.3)
        spans.append((t0, time.monotonic()))
        return {"ok": True}

    a = jobs.start("sync", "queue-test-a", ["x"], work)
    b = jobs.start("render", "queue-test-b", ["x"], work)
    time.sleep(0.1)
    assert b.to_dict()["status"] == "waiting" and "Waiting for the sync" in b.to_dict()["detail"]
    assert jobs.start("render", "queue-test-b", ["x"], work) is b  # same kind + match → the queued one
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and b.status != "done":
        time.sleep(0.05)
    assert a.status == b.status == "done"
    (s1, e1), (s2, e2) = sorted(spans)
    assert s2 >= e1  # no overlap


def test_cancelling_a_waiting_job_never_runs_it():
    ran = []
    blocker = jobs.start("export", "queue-test-c", ["x"], lambda j: time.sleep(0.4))
    queued = jobs.start("render", "queue-test-d", ["x"], lambda j: ran.append(1))
    jobs.cancel(queued)
    assert queued.status == "cancelled"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and blocker.status != "done":
        time.sleep(0.05)
    time.sleep(0.1)
    assert not ran


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Objects")
def test_children_die_with_the_app(tmp_path):
    """A child started after winjob.attach() is killed when the parent ends, even without any clean-up code."""
    script = tmp_path / "parent.py"
    script.write_text(
        "import subprocess, sys\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parent.parent)!r})\n"
        "from app import winjob\n"
        "assert winjob.attach()\n"
        "p = subprocess.Popen(['ping', '-n', '60', '127.0.0.1'], stdout=subprocess.DEVNULL)\n"
        "print(p.pid, flush=True)\n", encoding="utf-8")
    out = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=30)
    pid = int(out.stdout.strip())
    deadline = time.monotonic() + 5
    alive = True
    while time.monotonic() < deadline and alive:
        tl = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        alive = str(pid) in tl
        time.sleep(0.2)
    assert not alive, "child process outlived its parent"
