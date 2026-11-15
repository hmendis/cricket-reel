"""Phase 4 (R1, R5, R8, G1): fast start-up, librosa-free hit detection that matches the old results, version shown."""
import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from app import __version__, desktop, hits, main

ROOT = Path(__file__).resolve().parent.parent


def test_importing_the_app_does_not_load_the_heavy_packages():
    code = ("import sys, time; t = time.perf_counter(); import app.main; "
            "print(time.perf_counter() - t, [m for m in ('anthropic', 'PIL', 'librosa', 'pypdfium2') if m in sys.modules])")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60).stdout.split(" ", 1)
    seconds, loaded = float(out[0]), out[1].strip()
    assert loaded == "[]"
    assert seconds < 3.0  # about 0.7 s on the development laptop (was 7.4 s)


def _synth_wav(path: Path) -> np.ndarray:
    """The audio the librosa reference was made from (tests/fixtures/hits_librosa_synth.json)."""
    sr, dur = 22050, 120.0
    rng = np.random.default_rng(42)
    y = rng.normal(0, 0.01, int(sr * dur))
    hit_times = [8.0, 19.5, 31.0, 44.2, 55.0, 61.3, 77.7, 90.1, 101.0, 113.5]
    for t in hit_times:
        n = int(0.04 * sr)
        i = int(t * sr)
        y[i:i + n] += rng.normal(0, 0.6, n) * np.exp(-np.arange(n) / (0.008 * sr))
    for t in rng.uniform(1, 119, 40):
        n = int(0.03 * sr)
        i = int(t * sr)
        y[i:i + n] += rng.normal(0, 0.15, n) * np.exp(-np.arange(n) / (0.01 * sr))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())
    motion = np.full(int(dur * 10), 20.0)
    for t in hit_times:
        motion[int((t - 2.5) * 10):int(t * 10)] = 1.0
    return motion


def test_hit_detection_matches_the_librosa_version(tmp_path):
    ref = json.loads((ROOT / "tests" / "fixtures" / "hits_librosa_synth.json").read_text())
    motion = _synth_wav(tmp_path / "a.wav")
    got = hits.detect(tmp_path / "a.wav", motion, 10)
    assert len(got) == len(ref)
    for r, g in zip(ref, got):
        assert abs(r["t"] - g["t"]) <= 0.012 and abs(r["s"] - g["s"]) <= 0.01


def test_frame_features_are_block_size_independent(tmp_path, monkeypatch):
    _synth_wav(tmp_path / "a.wav")
    a = hits.frame_features(tmp_path / "a.wav")
    monkeypatch.setattr(hits, "BLOCK_FRAMES", 333)  # odd block size: block edges land everywhere
    b = hits.frame_features(tmp_path / "a.wav")
    for x, y in zip(a[1:], b[1:]):
        assert np.allclose(x, y, atol=1e-3)


def test_version_on_status_and_splash(tmp_data):
    assert __version__ == "2.2.0"
    assert TestClient(main.app).get("/api/status").json()["version"] == __version__
    assert "<svg" not in desktop.SPLASH and "__VERSION__" in desktop.SPLASH
