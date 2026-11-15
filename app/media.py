"""Media prep: one FFmpeg pass per match makes everything the analysis and the UI need.

From the source file(s), joined into one 25 fps timeline:
  work/proxy.mp4        540x960 H.264 + AAC, for smooth playback in the browser
  work/audio.wav        mono 22.05 kHz, for hit detection
  work/motion.npy       camera-motion level at 10 fps (from 48x84 grey frames)
  work/thumbs/NNNNN.jpg one 90x160 thumbnail per second, for the filmstrip
  work/waveform.json    peak level per 50 ms, for the timeline

Source files are never modified. A variable-frame-rate file is first converted to a constant 25 fps
working copy (work/cfr_NN.mp4); constant 25 fps files are read directly.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import threading
import time
import wave
from pathlib import Path

import numpy as np

from . import config

FPS = 25
MOTION_FPS = 10
MOTION_W, MOTION_H = 48, 84
_encoder_cache: dict[str, str] = {}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flash for FFmpeg in the desktop app


log = logging.getLogger(__name__)
_PROCS: set[subprocess.Popen] = set()   # every FFmpeg/FFprobe process still running
_PROCS_LOCK = threading.Lock()
_PROGRESS_LINE = re.compile(r"^[a-z_0-9]+=\S*$")


class MediaError(Exception):
    def __init__(self, message: str, stderr: str = ""):
        super().__init__(message)
        self.message, self.stderr = message, stderr


class Cancelled(Exception):
    pass


def ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise MediaError("FFmpeg isn't installed. Run: winget install -e --id Gyan.FFmpeg, then restart start.bat.")
    return exe


def h264_encoder() -> str:
    """'h264_qsv' if Intel Quick Sync works on this machine, else 'libx264'. If Quick Sync later fails on real
    footage, run() switches this to 'libx264' for the rest of the session."""
    if "h264" not in _encoder_cache:
        enc = "libx264"
        try:
            run([ffmpeg(), "-v", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.2", "-c:v", "h264_qsv",
                 "-f", "null", "-"], timeout=30, qsv_fallback=False)
            enc = "h264_qsv"
        except (MediaError, OSError):
            pass
        _encoder_cache["h264"] = enc
    return _encoder_cache["h264"]


def h264_args(quality: str = "proxy") -> list[str]:
    # The proxy gets a keyframe every second and no B-frames, so seeking (Review, preview renders, Look frames)
    # decodes at most 25 frames instead of up to 250.
    gop = ["-g", str(FPS), "-bf", "0"] if quality == "proxy" else []
    if h264_encoder() == "h264_qsv":
        return ["-c:v", "h264_qsv", "-global_quality", "28" if quality == "proxy" else "18", "-preset", "faster", *gop]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26" if quality == "proxy" else "16", *gop]


def source_path(match_dir: Path, v: dict) -> Path:
    """Where a match video is: a file linked in place (desktop import), or a copy in the match's source folder."""
    return Path(v["path"]) if v.get("linked") else match_dir / v["file"]


SPRITE = {"cols": 10, "rows": 10, "w": 90, "h": 160}  # R13: 100 one-per-second thumbnails per JPEG


def signature(videos: list[dict]) -> str:
    return "|".join(f"{v['file']}:{v['size']}" for v in videos)


class Result:
    def __init__(self, stdout: bytes, stderr: str):
        self.stdout, self.stderr = stdout, stderr


def run(cmd: list[str], *, total: float = 0.0, on_progress=None, cancel: threading.Event | None = None,
        stdout_sink=None, capture: bool = False, cwd=None, timeout: float | None = None, qsv_fallback: bool = True) -> Result:
    """The one way the app runs FFmpeg/FFprobe.

    - No console window. Progress from `-progress pipe:2` lines (needs `total` seconds) goes to on_progress(fraction).
    - stdout goes to stdout_sink(bytes) as it arrives, or is returned in Result.stdout with capture=True.
    - Cancel (event) and timeout (seconds) kill the process and wait for it, so nothing is left running.
    - If a command using Quick Sync fails, it is retried once with libx264 and Quick Sync is switched off for
      the rest of the session.
    Raises Cancelled, or MediaError with the end of FFmpeg's error output.
    """
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE if (stdout_sink or capture) else subprocess.DEVNULL,
                            stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, cwd=str(cwd) if cwd else None,
                            creationflags=NO_WINDOW)
    with _PROCS_LOCK:
        _PROCS.add(proc)
    err: list[str] = []
    out = bytearray()

    def read_err():
        for raw in proc.stderr:
            line = raw.decode("utf-8", "replace").rstrip()
            if line.startswith("out_time_us=") and total > 0 and on_progress:
                try:
                    on_progress(min(1.0, int(line.split("=")[1]) / 1e6 / total))
                except ValueError:
                    pass
            elif line and not _PROGRESS_LINE.match(line):
                err.append(line)
                del err[:-400]

    def read_out():
        while True:
            chunk = proc.stdout.read(1 << 20)
            if not chunk:
                return
            if stdout_sink:
                stdout_sink(chunk)
            else:
                out.extend(chunk)

    readers = [threading.Thread(target=read_err, daemon=True)]
    if proc.stdout:
        readers.append(threading.Thread(target=read_out, daemon=True))
    for t in readers:
        t.start()
    deadline = time.monotonic() + timeout if timeout else None
    try:
        while proc.poll() is None:
            if cancel is not None and cancel.wait(0.1):
                raise Cancelled()
            if cancel is None:
                time.sleep(0.05)
            if deadline and time.monotonic() > deadline:
                raise MediaError(f"FFmpeg took longer than {timeout:.0f} s and was stopped.", "\n".join(err))
    finally:
        if proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                log.error("FFmpeg pid %s didn't exit after kill", proc.pid)
        for t in readers:
            t.join(timeout=5)
        with _PROCS_LOCK:
            _PROCS.discard(proc)
    stderr = "\n".join(err)
    if proc.returncode != 0:
        if qsv_fallback and "h264_qsv" in cmd and not (cancel is not None and cancel.is_set()):
            log.warning("Quick Sync failed (%s); retrying with libx264 and using it from now on", err[-1:] or proc.returncode)
            _encoder_cache["h264"] = "libx264"
            return run(software_fallback(cmd), total=total, on_progress=on_progress, cancel=cancel,
                       stdout_sink=stdout_sink, capture=capture, cwd=cwd, timeout=timeout, qsv_fallback=False)
        tail = [l for l in err if l.strip()][-3:]
        raise MediaError("FFmpeg failed: " + (" / ".join(tail) or f"exit code {proc.returncode}"), stderr)
    return Result(bytes(out), stderr)


def software_fallback(cmd: list[str]) -> list[str]:
    """The same command with Intel Quick Sync swapped for libx264 (same quality setting)."""
    out, i = [], 0
    while i < len(cmd):
        a, nxt = cmd[i], cmd[i + 1] if i + 1 < len(cmd) else None
        if a == "-c:v" and nxt == "h264_qsv":
            out += ["-c:v", "libx264"]
        elif a == "-global_quality":
            out += ["-crf", nxt]
        elif a == "-pix_fmt" and nxt == "nv12":
            out += ["-pix_fmt", "yuv420p"]
        elif a in ("-look_ahead", "-async_depth", "-low_power", "-hwaccel_output_format") or (a == "-hwaccel" and nxt == "qsv"):
            pass
        else:
            out.append(a)
            i += 1
            continue
        i += 2
    return out


def kill_all() -> None:
    """Kill every FFmpeg process still running (used when the app closes)."""
    with _PROCS_LOCK:
        procs = list(_PROCS)
    for p in procs:
        if p.poll() is None:
            p.kill()
    for p in procs:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def prepare(match_dir: Path, videos: list[dict], on_progress, cancel: threading.Event) -> dict:
    """Build proxy/audio/motion/thumbs/waveform. Skips work already done for the same video list."""
    work = match_dir / "work"
    work.mkdir(exist_ok=True)
    state_file = work / "media.json"
    sig = signature(videos)
    state = config.read_json(state_file, {}) or {}
    needed = ["proxy.mp4", "audio.wav", "motion.npy", "waveform.json"]
    if state.get("signature") == sig and all((work / n).exists() for n in needed):
        on_progress(1.0)
        return state
    if not videos:
        raise MediaError("Add the match video first.")
    for v in videos:
        if not (v.get("probe") or {}).get("ok"):
            raise MediaError(f"{v['name']} couldn't be read as a video. Remove it and add it again.")

    total = sum(v["probe"]["duration"] for v in videos)
    # Everything is built in a stage folder and only swapped in once the whole pass succeeded, so a failed or
    # cancelled run never leaves a half-made proxy, missing thumbnails or partial files behind.
    for old in list(work.glob("*.part.*")) + [work / "thumbs.old"]:
        shutil.rmtree(old, ignore_errors=True) if old.is_dir() else old.unlink(missing_ok=True)
    stage = work / "prep.new"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir()
    try:
        state = _prepare_into(stage, match_dir, work, videos, total, sig, on_progress, cancel)
        _swap_in(stage, work)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    config.write_json_atomic(state_file, state)
    on_progress(1.0)
    return state


def _swap_in(stage: Path, work: Path) -> None:
    try:
        for name in ("proxy.mp4", "audio.wav", "motion.npy", "waveform.json", "stance.u8"):
            if (stage / name).exists() or name != "stance.u8":
                config.replace_with_retry(stage / name, work / name)
    except PermissionError as e:
        raise MediaError("The preview video is open somewhere else (another window or player). Close it and run the "
                         "sync again.") from e
    old = work / "thumbs"
    if old.exists():
        old.rename(work / "thumbs.old")
    (stage / "thumbs").rename(old)
    shutil.rmtree(work / "thumbs.old", ignore_errors=True)


def _prepare_into(stage: Path, match_dir: Path, work: Path, videos, total, sig, on_progress, cancel) -> dict:
    # 1. Constant-frame-rate working copies where needed (VFR or not 25 fps). Kept between runs.
    inputs, done_s = [], 0.0
    for i, v in enumerate(videos):
        src = source_path(match_dir, v)
        if not src.exists():
            raise MediaError(f"{v['name']} isn't where it was ({src}). Find it again on the import screen.")
        p = v["probe"]
        # Only variable-frame-rate files need a working copy; a constant 30/50/60 fps file is read directly
        # (the fps filter below and in every render makes 25 fps).
        if p.get("vfr"):
            cfr = work / f"cfr_{i + 1:02d}.mp4"
            if not cfr.exists():
                tmp = stage / cfr.name
                share = p["duration"] / total * 0.5
                run([ffmpeg(), "-v", "error", "-nostats", "-progress", "pipe:2", "-y", "-hwaccel", "auto", "-i", str(src),
                     "-vf", f"fps={FPS}", *h264_args("master"), "-c:a", "aac", "-b:a", "192k", str(tmp)],
                    total=p["duration"], on_progress=lambda f, d=done_s, s=share: on_progress((d / total * 0.5) + f * s),
                    cancel=cancel)
                config.replace_with_retry(tmp, cfr)
            src = cfr
        inputs.append(src)
        done_s += p["duration"]
    base = 0.5 if any(c.name.startswith("cfr_") for c in inputs) else 0.0

    # 2. One pass: proxy + audio + motion frames + thumbnails.
    n = len(inputs)
    cmd = [ffmpeg(), "-v", "error", "-nostats", "-progress", "pipe:2", "-y"]
    for src in inputs:
        cmd += ["-hwaccel", "auto", "-i", str(src)]
    cat = ("".join(f"[{i}:v:0]fps={FPS},setsar=1[iv{i}];" for i in range(n))
           + "".join(f"[iv{i}][{i}:a:0]" for i in range(n)) + f"concat=n={n}:v=1:a=1[cv][ca]")
    thumbs = stage / "thumbs"
    thumbs.mkdir()
    from . import stance
    # Scale to the proxy size once, then make the small outputs from that (was three scales from full size).
    fc = (f"{cat};[cv]fps={FPS},scale=540:960,split=4[pv][v2][v3][v4];"
          f"[v2]fps={MOTION_FPS},scale={MOTION_W}:{MOTION_H},format=gray[mv];"
          f"[v3]fps=1,scale={SPRITE['w']}:{SPRITE['h']},tile={SPRITE['cols']}x{SPRITE['rows']}[tv];"
          f"{stance.filter_branch('[v4]', '[sv]')};"
          f"[ca]asplit=2[pa][wa];[wa]aresample=22050,pan=mono|c0=0.5*c0+0.5*c1[wav]")
    if n == 1 and videos[0]["probe"].get("has_audio") is False:
        raise MediaError("The video has no audio track, so bat hits can't be found.")
    cmd += ["-filter_complex", fc,
            "-map", "[pv]", "-map", "[pa]", *h264_args("proxy"), "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            str(stage / "proxy.mp4"),
            "-map", "[wav]", "-c:a", "pcm_s16le", str(stage / "audio.wav"),
            "-map", "[tv]", "-q:v", "5", "-start_number", "0", str(thumbs / "sprite_%03d.jpg"),
            "-map", "[sv]", "-f", "rawvideo", str(stage / stance.FILE),
            "-map", "[mv]", "-f", "rawvideo", "pipe:1"]
    sink = MotionSink()
    run(cmd, total=total, on_progress=lambda f: on_progress(base + f * (1 - base) * 0.97), cancel=cancel, stdout_sink=sink)
    np.save(stage / "motion.npy", sink.result())
    write_waveform(stage / "audio.wav", stage / "waveform.json")
    return {"signature": sig, "duration": total, "fps": FPS, "encoder": h264_encoder(),
            "offsets": _offsets(videos), "motion_fps": MOTION_FPS, "thumbs": {"sprite": True, **SPRITE},
            "working_copies": [i + 1 for i, v in enumerate(videos) if v["probe"].get("vfr")]}


class MotionSink:
    """Turns the raw grey motion frames from FFmpeg into one number per frame as they arrive: the mean absolute
    difference from the previous frame. Only the previous frame is kept, so memory doesn't grow with the match."""

    def __init__(self, w: int = MOTION_W, h: int = MOTION_H):
        self.size = w * h
        self.rest = b""
        self.prev: np.ndarray | None = None
        self.values: list[float] = []

    def __call__(self, chunk: bytes) -> None:
        data = self.rest + chunk
        k = len(data) // self.size
        self.rest = data[k * self.size:]
        if not k:
            return
        frames = np.frombuffer(data, np.uint8, count=k * self.size).reshape(k, self.size).astype(np.float32)
        if self.prev is None:
            self.values.append(0.0)
            diffs = np.abs(np.diff(frames, axis=0)).mean(axis=1)
        else:
            diffs = np.abs(np.diff(np.vstack([self.prev[None], frames]), axis=0)).mean(axis=1)
        self.values.extend(diffs.tolist())
        self.prev = frames[-1]

    def result(self) -> np.ndarray:
        return np.array(self.values or [0.0], np.float32)


def _offsets(videos):
    out, t = [], 0.0
    for v in videos:
        out.append({"file": v["file"], "path": str(v["path"]) if v.get("linked") else None, "start": round(t, 3),
                    "duration": v["probe"]["duration"]})
        t += v["probe"]["duration"]
    return out


def write_waveform(wav: Path, out: Path, step: float = 0.05):
    """Peak level per `step` seconds, read in blocks so memory stays flat for long matches."""
    with wave.open(str(wav), "rb") as w:
        sr = w.getframerate()
        hop = int(sr * step)
        parts, carry = [], np.zeros(0, np.float32)
        while True:
            raw = w.readframes(hop * 2000)
            if not raw:
                break
            y = np.concatenate([carry, np.abs(np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0)])
            k = len(y) // hop
            if k:
                parts.append(y[: k * hop].reshape(k, hop).max(axis=1))
            carry = y[k * hop:]
    peaks = np.concatenate(parts) if parts else np.zeros(0)
    top = float(np.percentile(peaks, 99.5)) if len(peaks) else 1.0
    vals = np.clip(peaks / (top or 1.0), 0, 1)
    out.write_text(json.dumps({"step": step, "peaks": [round(float(v), 3) for v in vals]}, separators=(",", ":")), encoding="utf-8")
    out.with_suffix(".bin").write_bytes(np.round(vals * 255).astype(np.uint8).tobytes())  # R16: one byte per step
