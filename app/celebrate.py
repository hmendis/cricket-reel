"""Find the celebration after a wicket in the field (2.1).

From the field the bat-hit detector is useless (about 60 false hits a minute), so wickets are placed from the sheet
order and refined by the noise after them. A celebration is sustained voice-band (300-3400 Hz) energy more than 3 dB
above a 60 s rolling baseline for about 4 s, usually with a rise in pitch, some claps and the head-cam moving.

Everything is computed once per recording on 0.1 s bins and cached in work/celebrate.npz.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.ndimage import median_filter

from .hits import HOP, N_FFT, _stft_blocks

BIN = 0.1                 # seconds per feature bin
VOICE_HZ = (300, 3400)
CLAP_HZ = (2000, 8000)
BASELINE_S = 60.0         # rolling baseline window
SUSTAIN_S = 4.0           # a celebration lasts about this long
MIN_DB = 3.0              # sustained voice energy above the baseline needed to call it a celebration
CLAP_JUMP_DB = 10.0       # a clap: high band jumps this much over the last half second, then drops again
FADE_DB = 1.5             # the celebration has faded when the voice excess drops under this
VERSION = 2
F0_HZ = (80, 500)          # where a shouting voice's fundamental is
AMIN = 1e-10


def features(wav_path: Path, motion: np.ndarray | None = None, motion_fps: int = 10) -> dict:
    """Per 0.1 s bin: voice-band dB, its 60 s baseline, a rough voice f0 (for the pitch rise), clap onsets and
    head-cam motion. Reads the WAV in blocks, so memory stays flat for a long match."""
    voice = cent = hf = None
    sr = 22050
    for sr, n_frames, start, S in _stft_blocks(wav_path):
        if voice is None:
            freqs = np.fft.rfftfreq(N_FFT, 1 / sr)
            vb = (freqs >= VOICE_HZ[0]) & (freqs <= VOICE_HZ[1])
            hb = (freqs >= CLAP_HZ[0]) & (freqs <= CLAP_HZ[1])
            fb = (freqs >= F0_HZ[0]) & (freqs <= F0_HZ[1])
            ff = freqs[fb]
            voice, cent, hf = (np.zeros(n_frames, np.float32) for _ in range(3))
        k = len(S)
        p = S ** 2
        pv = p[:, vb]
        voice[start:start + k] = pv.sum(1)
        cent[start:start + k] = ff[np.argmax(S[:, fb], axis=1)]          # strongest low peak: a rough f0
        hf[start:start + k] = p[:, hb].sum(1)
    if voice is None:
        return _empty()
    fps = sr / HOP                                   # STFT frames per second (~86)
    nb = int(np.ceil(len(voice) / fps / BIN))
    idx = np.minimum(nb - 1, (np.arange(len(voice)) / fps / BIN).astype(int))
    cnt = np.maximum(1, np.bincount(idx, minlength=nb))
    vbin = np.bincount(idx, voice, nb) / cnt
    cbin = np.bincount(idx, cent * voice, nb) / np.maximum(AMIN, np.bincount(idx, voice, nb))   # f0, weighted by loudness
    vdb = 10 * np.log10(np.maximum(AMIN, vbin))
    base = median_filter(vdb, size=max(3, int(BASELINE_S / BIN)), mode="nearest")
    # claps: short high-band spikes, counted per bin
    hdb = 10 * np.log10(np.maximum(AMIN, hf))
    size = max(3, int(0.5 * fps))
    centred = median_filter(hdb, size=size, mode="nearest")
    half = size // 2 + 1                              # shift so each frame is compared with the half second before it
    ref = np.concatenate([np.full(half, centred[0] if len(centred) else 0, np.float32), centred[:-half]]) if len(hdb) > half else centred
    after = np.concatenate([hdb[int(0.08 * fps):], np.full(int(0.08 * fps), hdb[-1] if len(hdb) else 0)])
    onset = (hdb - ref > CLAP_JUMP_DB) & (hdb - after > CLAP_JUMP_DB / 2)
    onset[1:] &= ~onset[:-1]                         # one count per spike
    claps = np.bincount(idx[onset], minlength=nb).astype(np.float32)
    mot = np.zeros(nb, np.float32)
    if motion is not None and len(motion):
        t = np.arange(nb) * BIN
        mot = np.interp(t, np.arange(len(motion)) / motion_fps, motion).astype(np.float32)
    mbase = median_filter(mot, size=max(3, int(BASELINE_S / BIN)), mode="nearest") if len(mot) else mot
    return {"version": VERSION, "bin": BIN, "voice_db": vdb.astype(np.float32), "base_db": base.astype(np.float32),
            "f0": cbin.astype(np.float32), "claps": claps,
            "motion": mot, "motion_base": mbase.astype(np.float32)}


def _empty() -> dict:
    z = np.zeros(0, np.float32)
    return {"version": VERSION, "bin": BIN, "voice_db": z, "base_db": z, "f0": z, "claps": z, "motion": z, "motion_base": z}


def load_or_compute(work: Path, signature: str, motion_fps: int = 10) -> dict:
    """Features for this recording, from work/celebrate.npz when it was made from the same media."""
    f = work / "celebrate.npz"
    if f.exists():
        try:
            z = np.load(f)
            if str(z["signature"]) == signature and int(z["version"]) == VERSION:
                return {k: z[k] for k in z.files if k not in ("signature",)} | {"version": VERSION, "bin": float(z["bin"])}
        except (OSError, KeyError, ValueError):
            pass
    motion = np.load(work / "motion.npy") if (work / "motion.npy").exists() else None
    F = features(work / "audio.wav", motion, motion_fps)
    tmp = work / "celebrate.part.npz"
    np.savez(tmp, signature=np.array(signature), **{k: v for k, v in F.items()})
    tmp.replace(f)
    return F


def _mean(a: np.ndarray, i: int, n: int) -> float:
    seg = a[i:i + n]
    return float(seg.mean()) if len(seg) else 0.0


def at(F: dict, t: float) -> dict:
    """How celebration-like the SUSTAIN_S seconds from t are: voice excess (dB), pitch rise (Hz: the voice's f0 in its
    last two seconds against its first second), claps, motion."""
    i, n = int(round(t / F["bin"])), int(SUSTAIN_S / F["bin"])
    if i < 0 or i >= len(F["voice_db"]):
        return {"t": t, "db": 0.0, "pitch": 0.0, "claps": 0, "motion": 0.0, "score": 0.0}
    db = _mean(F["voice_db"], i, n) - _mean(F["base_db"], i, n)
    one = int(1 / F["bin"])
    pitch = _mean(F["f0"], i + 2 * one, 2 * one) - _mean(F["f0"], i, one)
    claps = int(F["claps"][i:i + int(5 / F["bin"])].sum())
    mb = _mean(F["motion_base"], i, n)
    motion = (_mean(F["motion"], i, n) / mb) if mb > 0 else 1.0
    score = (np.clip(db / 6, 0, 1) * 0.6 + np.clip(pitch / 40, 0, 1) * 0.15 + min(claps, 4) / 4 * 0.15
             + np.clip((motion - 1) / 1.5, 0, 1) * 0.1)
    return {"t": round(t, 2), "db": round(db, 1), "pitch": round(pitch), "claps": claps, "motion": round(motion, 2), "score": round(float(score), 3)}


def find(F: dict, t0: float, t1: float) -> dict | None:
    """The best celebration start in [t0, t1]: the bin with the most sustained voice excess (score breaks ties).
    None when the window is outside the recording."""
    b = F["bin"]
    lo, hi = max(0, int(t0 / b)), min(len(F["voice_db"]) - 1, int(t1 / b))
    if hi <= lo:
        return None
    n = int(SUSTAIN_S / b)
    ex = F["voice_db"] - F["base_db"]
    c = np.concatenate([[0.0], np.cumsum(ex, dtype=np.float64)])
    ends = np.minimum(len(ex), np.arange(lo, hi + 1) + n)
    sustained = (c[ends] - c[lo:hi + 1]) / np.maximum(1, ends - np.arange(lo, hi + 1))
    # the start of a celebration: where the sustained excess first comes within 1 dB of its best in the window
    best = float(sustained.max())
    i = lo + int(np.argmax(sustained >= best - 1.0))
    return at(F, i * b)


def fade(F: dict, t: float, max_s: float = 6.0) -> float:
    """Seconds from t until the voice excess has stayed under FADE_DB for half a second (at most max_s)."""
    b = F["bin"]
    ex = F["voice_db"] - F["base_db"]
    i0 = int(t / b)
    quiet = 0
    for k in range(i0, min(len(ex), i0 + int(max_s / b))):
        quiet = quiet + 1 if ex[k] < FADE_DB else 0
        if quiet >= int(0.5 / b):
            return (k - quiet + 1 - i0) * b
    return max_s
