"""Bat-hit candidates from the audio, scored with a little help from camera motion.

Audio: onsets in the 1.5-8 kHz band (where a bat crack lives), each scored on how much it stands out
from the surrounding 10 s, how sharp the attack is, and how loud it is.
Motion (head camera): a batter stands still in their stance (or the non-striker waits) for a second or
more before the ball arrives, then moves. An onset right after such a still spell is far more likely to
be a delivery than one during walking about or chatting between overs.

The audio is read in blocks (twice), so memory stays flat however long the match is: only three numbers
per 11.6 ms frame are kept (band onset, band energy, RMS). Plain numpy/scipy; this used to be librosa
(same STFT, onset strength, RMS and peak picking), which pulled numba/llvmlite/scikit-learn into the app.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

DEFAULTS = {
    "band_hz": [1500, 8000],
    "min_gap_s": 0.25,      # two candidates can't be closer than this
    "audio_weight": 0.55,
    "motion_weight": 0.45,
    "sensitivity": 0.5,     # 0..1 - lower keeps fewer, stronger candidates
}
N_FFT, HOP = 1024, 256
BLOCK_FRAMES = 2048          # STFT frames per block (~24 s of audio at 22.05 kHz)
ONSET_SHIFT = 4              # librosa's onset centring for these settings: n_fft(2048) // (2 * hop)
AMIN, TOP_DB = 1e-5, 80.0


def _robust_z(x: np.ndarray, win: int) -> np.ndarray:
    """(x - rolling median) / rolling MAD over a window of frames."""
    from scipy.ndimage import median_filter
    med = median_filter(x, size=win, mode="nearest")
    mad = median_filter(np.abs(x - med), size=win, mode="nearest") + 1e-6
    return (x - med) / (1.4826 * mad)


def _stft_blocks(wav_path: Path):
    """Yield (sr, n_frames, start, |STFT|) per block of frames: centred frames, periodic hann window, as librosa.stft."""
    with wave.open(str(wav_path), "rb") as w:
        sr, n_total, width, ch = w.getframerate(), w.getnframes(), w.getsampwidth(), w.getnchannels()
        if width != 2:
            raise ValueError("Expected 16-bit audio")
        n_frames = 1 + n_total // HOP
        win = np.hanning(N_FFT + 1)[:-1].astype(np.float32)
        buf = np.zeros(N_FFT // 2, np.float32)       # centre padding before the first sample
        start, eof = 0, False
        while start < n_frames:
            need = (BLOCK_FRAMES - 1) * HOP + N_FFT
            while len(buf) < need and not eof:
                raw = w.readframes(BLOCK_FRAMES * HOP)
                if not raw:
                    eof = True
                    buf = np.concatenate([buf, np.zeros(N_FFT // 2, np.float32)])  # and after the last
                    break
                y = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
                if ch > 1:
                    y = y.reshape(-1, ch).mean(axis=1)
                buf = np.concatenate([buf, y])
            k = min(BLOCK_FRAMES, n_frames - start, max(0, (len(buf) - N_FFT) // HOP + 1))
            if k <= 0:
                return
            frames = np.lib.stride_tricks.sliding_window_view(buf[: (k - 1) * HOP + N_FFT], N_FFT)[::HOP][:k]
            yield sr, n_frames, start, np.abs(np.fft.rfft(frames * win, axis=1)).astype(np.float32)
            start += k
            buf = buf[k * HOP:]


def frame_features(wav_path: Path, band_hz=(1500, 8000)):
    """Return (sr, onset, band_energy, rms), one value per STFT frame, reading the WAV in blocks.

    Two passes over the file: the first finds the loudest band value (quiet bins are clipped 80 dB under it,
    as librosa does with ref=max), the second keeps three numbers per frame. Memory stays flat.
    """
    band = None
    top = AMIN
    for sr, n_frames, start, S in _stft_blocks(wav_path):
        if band is None:
            freqs = np.fft.rfftfreq(N_FFT, 1 / sr)
            band = (freqs >= band_hz[0]) & (freqs <= band_hz[1])
        top = max(top, float(S[:, band].max()))
    if band is None:
        return 22050, np.zeros(0, np.float32), np.zeros(0, np.float32), np.zeros(0, np.float32)
    floor = 20 * np.log10(top) - TOP_DB
    onset_raw = e_band = rms = None
    prev_db = None
    for sr, n_frames, start, S in _stft_blocks(wav_path):
        if onset_raw is None:
            onset_raw, e_band, rms = (np.zeros(n_frames, np.float32) for _ in range(3))
        k = len(S)
        Sb = S[:, band]
        e_band[start:start + k] = Sb.sum(1)
        p = S ** 2
        p[:, 0] *= 0.5
        p[:, -1] *= 0.5
        rms[start:start + k] = np.sqrt(2 * p.sum(1) / N_FFT ** 2)
        db = np.maximum(20 * np.log10(np.maximum(AMIN, Sb)), floor)
        both = db if prev_db is None else np.vstack([prev_db[None], db])
        diff = np.maximum(0.0, np.diff(both, axis=0)).mean(1)
        if prev_db is None:
            onset_raw[start + 1:start + k] = diff
        else:
            onset_raw[start:start + k] = diff
        prev_db = db[-1]
    n_frames = len(onset_raw)
    # librosa pads the onset envelope by lag + centring shift: out[t] = change into frame t - ONSET_SHIFT
    onset = np.zeros(n_frames, np.float32)
    onset[ONSET_SHIFT:] = onset_raw[: n_frames - ONSET_SHIFT]
    return sr, onset, e_band, rms


def peak_pick(x: np.ndarray, pre_max: int, post_max: int, pre_avg: int, post_avg: int, delta: float, wait: int) -> np.ndarray:
    """Same rule as librosa.util.peak_pick: a local max that beats the moving average by delta, at least `wait` apart."""
    from scipy.ndimage import maximum_filter1d, uniform_filter1d
    mov_max = maximum_filter1d(x, pre_max + post_max, mode="constant", origin=int(np.ceil(0.5 * (pre_max - post_max))),
                               cval=float(x.min()))
    mov_avg = uniform_filter1d(x, pre_avg + post_avg, mode="nearest", origin=int(np.ceil(0.5 * (pre_avg - post_avg))))
    n = len(x)
    for i in list(range(min(pre_avg, n))) + list(range(max(0, n - post_avg), n)):
        mov_avg[i] = x[max(0, i - pre_avg): i + post_avg].mean()
    det = x * (x == mov_max)
    det = det * (det >= mov_avg + delta)
    peaks, last = [], -np.inf
    for i in np.nonzero(det)[0]:
        if i > last + wait:
            peaks.append(i)
            last = i
    return np.array(peaks, int)


def _to_db(x: np.ndarray, ref: float) -> np.ndarray:
    db = 20 * np.log10(np.maximum(AMIN, x) / max(ref, AMIN))
    return np.maximum(db, db.max() - TOP_DB)


def detect(wav_path, motion: np.ndarray | None, motion_fps: int = 10, params: dict | None = None) -> list[dict]:
    p = {**DEFAULTS, **(params or {})}
    sr, onset, e_band, rms = frame_features(Path(wav_path), p["band_hz"])
    if len(onset) * HOP < sr:
        return []
    e_band = e_band.astype(np.float64) + 1e-9
    fps = sr / HOP
    times = np.arange(len(onset)) / fps

    raw = peak_pick(onset, 3, 3, int(fps), int(fps), 0.3, 1)
    if len(raw) == 0:
        return []
    # Keep the STRONGEST peak within min_gap (a plain `wait` keeps the earliest, which lets a small
    # blip just before a crack hide the crack itself).
    gap = max(1, int(p["min_gap_s"] * fps))
    taken = np.zeros(len(onset), bool)
    peaks = []
    for k in sorted(raw, key=lambda k: -onset[k]):
        if not taken[max(0, k - gap):k + gap + 1].any():
            peaks.append(k)
            taken[k] = True
    peaks = np.array(sorted(peaks))
    z_on = _robust_z(onset, int(10 * fps) | 1)
    loud_db = _to_db(rms, float(np.percentile(rms, 99)))

    feats = []
    for k in peaks:
        pre = np.median(e_band[max(0, k - 20):k]) if k > 0 else e_band[k]
        sharp = float(e_band[k:k + 3].max() / (pre + 1e-9))
        feats.append((times[k], z_on[k], np.log1p(sharp), loud_db[k:k + 3].max()))
    f = np.array(feats)

    def norm(col, lo, hi):
        return np.clip((col - lo) / (hi - lo), 0, 1)

    audio = 0.5 * norm(f[:, 1], 1, 8) + 0.3 * norm(f[:, 2], 0.5, 2.5) + 0.2 * norm(f[:, 3], -25, -3)

    still_b = np.zeros(len(f))
    move_a = np.zeros(len(f))
    if motion is not None and len(motion) > motion_fps * 3:
        sm = np.convolve(motion, np.ones(3) / 3, mode="same")
        thr = 0.55 * float(np.median(sm))  # "still" = well under the camera's typical movement
        for i, t in enumerate(f[:, 0]):
            a, b = int((t - 2.2) * motion_fps), int((t - 0.4) * motion_fps)
            c, d = int(t * motion_fps), int((t + 1.2) * motion_fps)
            if a >= 0 and d < len(sm):
                still_b[i] = float((sm[a:b] < thr).mean())
                move_a[i] = float(np.clip(sm[c:d].mean() / (thr * 2.5), 0, 1))
        # A delivery is the END of a still spell: still before AND moving after (product, not sum).
        motion_score = np.sqrt(still_b * move_a)
        score = p["audio_weight"] * audio + p["motion_weight"] * motion_score
    else:
        motion_score = np.zeros(len(f))
        score = audio

    keep = score >= np.quantile(score, 1 - (0.15 + 0.5 * p["sensitivity"]))  # keep the top 40% by default
    out = []
    for i in np.where(keep)[0]:
        out.append({"t": round(float(f[i, 0]), 3), "s": round(float(score[i]), 3), "audio": round(float(audio[i]), 3),
                    "motion": round(float(motion_score[i]), 3), "still": round(float(still_b[i]), 2), "move": round(float(move_a[i]), 2)})
    return out
